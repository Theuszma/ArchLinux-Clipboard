"""Leitura e escrita do clipboard do sistema.

Wayland usa wl-clipboard (wl-paste/wl-copy); X11 usa xclip. Em ambos os casos
falamos com o processo externo em vez da API do GDK, porque no Wayland um
cliente só recebe eventos de seleção enquanto tem foco de teclado -- inútil
para um daemon que fica em segundo plano.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional

# Ordem de preferência ao decidir o que guardar de uma seleção.
IMAGE_TYPES = ("image/png", "image/webp", "image/jpeg", "image/bmp", "image/tiff")
TEXT_TYPES = (
    "text/plain;charset=utf-8",
    "UTF8_STRING",
    "text/plain",
    "STRING",
    "TEXT",
)

# Gerenciadores de senha marcam a seleção com este tipo para pedir que
# históricos de clipboard a ignorem.
PASSWORD_HINT = "x-kde-passwordManagerHint"

TIMEOUT = 5


def is_wayland() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY")) or (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    )


class ClipboardError(RuntimeError):
    pass


class Backend:
    """Interface mínima de um backend de clipboard."""

    name = "none"

    def list_types(self) -> list[str]:
        raise NotImplementedError

    def read(self, mime: str) -> bytes:
        raise NotImplementedError

    def write(self, data: bytes, mime: str) -> None:
        raise NotImplementedError

    def watch_command(self) -> Optional[list[str]]:
        """Comando que emite uma linha em stdout a cada mudança, se houver."""
        return None


class WaylandBackend(Backend):
    name = "wayland"

    def list_types(self) -> list[str]:
        result = subprocess.run(
            ["wl-paste", "--list-types"],
            capture_output=True,
            timeout=TIMEOUT,
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.decode("utf-8", "replace").splitlines() if line.strip()]

    def read(self, mime: str) -> bytes:
        result = subprocess.run(
            ["wl-paste", "--no-newline", "--type", mime],
            capture_output=True,
            timeout=TIMEOUT,
        )
        if result.returncode != 0:
            raise ClipboardError(result.stderr.decode("utf-8", "replace").strip())
        return result.stdout

    def write(self, data: bytes, mime: str) -> None:
        # wl-copy se destaca em segundo plano para continuar servindo o dado,
        # como o protocolo do Wayland exige.
        result = subprocess.run(
            ["wl-copy", "--type", mime],
            input=data,
            capture_output=True,
            timeout=TIMEOUT,
        )
        if result.returncode != 0:
            raise ClipboardError(result.stderr.decode("utf-8", "replace").strip())

    def watch_command(self) -> list[str]:
        # `--watch` roda o comando a cada mudança; /usr/bin/echo devolve uma
        # linha vazia, que usamos apenas como sinal ("mudou, vá ler").
        return ["wl-paste", "--watch", "/usr/bin/echo"]


class X11Backend(Backend):
    name = "x11"

    def list_types(self) -> list[str]:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", "TARGETS", "-o"],
            capture_output=True,
            timeout=TIMEOUT,
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.decode("utf-8", "replace").splitlines() if line.strip()]

    def read(self, mime: str) -> bytes:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", mime, "-o"],
            capture_output=True,
            timeout=TIMEOUT,
        )
        if result.returncode != 0:
            raise ClipboardError(result.stderr.decode("utf-8", "replace").strip())
        return result.stdout

    def write(self, data: bytes, mime: str) -> None:
        process = subprocess.Popen(
            ["xclip", "-selection", "clipboard", "-t", mime],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        process.communicate(data, timeout=TIMEOUT)


def detect_backend() -> tuple[Optional[Backend], str]:
    """Escolhe o backend disponível. Retorna (backend, mensagem_de_erro)."""
    if is_wayland():
        if not shutil.which("wl-paste") or not shutil.which("wl-copy"):
            return None, (
                "wl-clipboard não encontrado. Instale com: sudo pacman -S wl-clipboard"
            )
        return WaylandBackend(), ""
    if not shutil.which("xclip"):
        return None, "xclip não encontrado. Instale com: sudo pacman -S xclip"
    return X11Backend(), ""


def pick_type(types: list[str], want_text: bool, want_images: bool) -> Optional[str]:
    """Melhor tipo MIME a guardar, ou None se nada interessa."""
    lowered = {t.lower(): t for t in types}
    if want_images:
        for candidate in IMAGE_TYPES:
            if candidate in lowered:
                return lowered[candidate]
    if want_text:
        for candidate in TEXT_TYPES:
            if candidate.lower() in lowered:
                return lowered[candidate.lower()]
        # Qualquer text/* serve como último recurso.
        for lower, original in lowered.items():
            if lower.startswith("text/"):
                return original
    return None


def is_sensitive(types: list[str]) -> bool:
    """True se a seleção pede para não ser guardada no histórico."""
    return any(t.lower().startswith(PASSWORD_HINT.lower()) for t in types)
