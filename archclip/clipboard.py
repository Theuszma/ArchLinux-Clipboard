"""Leitura e escrita do clipboard do sistema.

Três backends, nesta ordem de preferência:

- GNOME Shell (`shellext`), via a extensão em `extension/`. É o único que
  enxerga o clipboard em segundo plano no GNOME, porque o Mutter não
  implementa data-control.
- wl-clipboard (wl-paste/wl-copy), para os compositores que implementam.
- xclip, no X11.

Falamos com processos externos em vez da API do GDK porque no Wayland um
cliente só recebe eventos de seleção enquanto tem foco de teclado -- inútil
para um daemon que fica em segundo plano.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Callable, Optional

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

    def watch_signal(self, on_change) -> Optional[Callable[[], None]]:
        """Assina um evento de mudança, se o backend tiver um.

        Devolve a função que cancela a assinatura, ou None quando o backend
        não sabe avisar sozinho -- aí o monitor cai no `watch_command` ou no
        polling.
        """
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


def shell_backend() -> Optional[Backend]:
    """Backend da extensão do GNOME Shell, se ela estiver no ar.

    Import tardio: `shellext` precisa do GIO, e este módulo é usado (e
    testado) em lugares onde o PyGObject pode não existir.
    """
    try:
        from . import shellext
    except ImportError:
        return None
    return shellext.connect()


def detect_backend() -> tuple[Optional[Backend], str]:
    """Escolhe o backend disponível. Retorna (backend, mensagem_de_erro)."""
    if is_wayland():
        # No GNOME é o único caminho que enxerga o clipboard em segundo
        # plano; nos demais compositores nem chega a existir e o wl-clipboard
        # assume, com o data-control que eles implementam.
        shell = shell_backend()
        if shell is not None:
            return shell, ""
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
