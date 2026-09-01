"""Ponte com a extensão do GNOME Shell (diretório `extension/`).

O Mutter não implementa data-control -- nem `wlr-data-control-unstable-v1`
nem `ext-data-control-v1` --, então `wl-paste --watch` não funciona no GNOME e
um cliente comum só recebe eventos de seleção enquanto tem foco de teclado.
Quem consegue vigiar a área de transferência em segundo plano é código
rodando dentro do próprio Shell, e é isso que a extensão faz: ela publica o
serviço `io.github.theuszma.ArchClip.Shell` na sessão, e daqui só falamos
D-Bus com ela.

A política continua toda deste lado -- o que capturar, o limite de tamanho, a
dica de gerenciador de senha --, porque é aqui que mora a configuração do
usuário. A extensão só entrega tipos MIME e bytes.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

# Não passamos pelo `gtkdeps` de propósito: ele carrega GTK e libadwaita e
# aborta o processo quando o PyGObject não está instalado. Aqui só o GIO é
# necessário, e quem importa este módulo trata o ImportError.
from gi.repository import Gio, GLib

from .clipboard import Backend, ClipboardError
from .util import SHELL_EXTENSION_DIR, SHELL_EXTENSION_UUID

UUID = SHELL_EXTENSION_UUID
BUS_NAME = "io.github.theuszma.ArchClip.Shell"
OBJECT_PATH = "/io/github/theuszma/ArchClip/Shell"
INTERFACE = BUS_NAME

# `GetSelection` espera o aplicativo que publicou a seleção responder; a
# extensão desiste em 10 s, então esperamos um pouco mais que isso para a
# mensagem de erro vir dela, mais específica, e não do nosso timeout.
READ_TIMEOUT = 12000  # ms
CALL_TIMEOUT = 5000  # ms


def extension_dir() -> Path:
    """Onde o install.sh põe a extensão (diretório do usuário)."""
    return SHELL_EXTENSION_DIR


def installed_dirs() -> list[Path]:
    """Todos os lugares onde ela pode estar: o do usuário e os do sistema.

    Quem instalou pelo pacman/AUR tem a extensão em /usr/share, não em
    ~/.local/share -- e continua tendo a extensão instalada.
    """
    dirs = [SHELL_EXTENSION_DIR]
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    for base in data_dirs.split(":"):
        if base:
            dirs.append(Path(base) / "gnome-shell" / "extensions" / UUID)
    return dirs


def is_installed() -> bool:
    return any((path / "metadata.json").exists() for path in installed_dirs())


def is_gnome() -> bool:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    return "GNOME" in desktop.upper()


class ShellBackend(Backend):
    """Lê e escreve a seleção através da extensão do GNOME Shell."""

    name = "gnome-shell"

    def __init__(self, connection: Gio.DBusConnection) -> None:
        self._bus = connection

    def _call(
        self,
        method: str,
        params: Optional[GLib.Variant],
        reply_type: Optional[str],
        timeout: int = CALL_TIMEOUT,
    ) -> GLib.Variant:
        try:
            return self._bus.call_sync(
                BUS_NAME,
                OBJECT_PATH,
                INTERFACE,
                method,
                params,
                GLib.VariantType.new(reply_type) if reply_type else None,
                # Sem auto-start: ninguém pode subir a extensão sob demanda, e
                # esperar por isso só atrasaria o erro.
                Gio.DBusCallFlags.NO_AUTO_START,
                timeout,
                None,
            )
        except GLib.Error as exc:
            raise ClipboardError(
                "extensão do GNOME Shell: {}".format(exc.message)
            ) from exc

    def list_types(self) -> list[str]:
        reply = self._call("GetMimetypes", None, "(as)")
        return list(reply.get_child_value(0).unpack())

    def read(self, mime: str) -> bytes:
        reply = self._call(
            "GetSelection", GLib.Variant("(s)", (mime,)), "(ay)", timeout=READ_TIMEOUT
        )
        # Para o tipo 'ay' a forma serializada são os próprios bytes, sem
        # padding -- é o caminho barato, sem virar lista de inteiros.
        return reply.get_child_value(0).get_data_as_bytes().get_data() or b""

    def write(self, data: bytes, mime: str) -> None:
        self._call("SetSelection", GLib.Variant("(say)", (mime, data)), None)

    def watch_signal(self, on_change: Callable[[], None]) -> Callable[[], None]:
        def handler(*_args) -> None:
            on_change()

        subscription = self._bus.signal_subscribe(
            BUS_NAME,
            INTERFACE,
            "SelectionChanged",
            OBJECT_PATH,
            None,
            Gio.DBusSignalFlags.NONE,
            handler,
        )

        def unsubscribe() -> None:
            self._bus.signal_unsubscribe(subscription)

        return unsubscribe


def session_bus() -> Optional[Gio.DBusConnection]:
    try:
        return Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error:
        return None


def service_running(connection: Optional[Gio.DBusConnection] = None) -> bool:
    """True se a extensão está no ar (instalada, ligada e com o Shell rodando)."""
    bus = connection or session_bus()
    if bus is None:
        return False
    try:
        reply = bus.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "NameHasOwner",
            GLib.Variant("(s)", (BUS_NAME,)),
            GLib.VariantType.new("(b)"),
            Gio.DBusCallFlags.NONE,
            CALL_TIMEOUT,
            None,
        )
    except GLib.Error:
        return False
    return bool(reply.get_child_value(0).get_boolean())


def connect() -> Optional[ShellBackend]:
    """Backend da extensão, ou None se ela não estiver publicada na sessão."""
    bus = session_bus()
    if bus is None or not service_running(bus):
        return None
    return ShellBackend(bus)


def has_method(name: str, connection: Optional[Gio.DBusConnection] = None) -> bool:
    """True se a extensão que está no ar declara esse método.

    O daemon e a extensão podem estar em versões diferentes: o GNOME Shell só
    carrega o código novo no login seguinte, então uma atualização deixa os
    dois fora de sincronia por um tempo. Perguntar sai mais barato que
    descobrir pelo erro na cara do usuário.
    """
    bus = connection or session_bus()
    if bus is None:
        return False
    try:
        reply = bus.call_sync(
            BUS_NAME,
            OBJECT_PATH,
            "org.freedesktop.DBus.Introspectable",
            "Introspect",
            None,
            GLib.VariantType.new("(s)"),
            Gio.DBusCallFlags.NO_AUTO_START,
            CALL_TIMEOUT,
            None,
        )
    except GLib.Error:
        return False
    return '<method name="{}"'.format(name) in reply.get_child_value(0).get_string()


def set_window_above(above: bool, connection: Optional[Gio.DBusConnection] = None) -> str:
    """Pede à extensão que mantenha (ou pare de manter) a janela por cima.

    No Wayland quem decide empilhamento é o compositor -- um app comum não
    tem como se colocar acima dos outros. Dentro do Shell isso é uma chamada
    de `MetaWindow`. Retorna "" ou a mensagem de erro.
    """
    bus = connection or session_bus()
    if bus is None:
        return "sem barramento de sessão"
    try:
        bus.call_sync(
            BUS_NAME,
            OBJECT_PATH,
            INTERFACE,
            "SetWindowAbove",
            GLib.Variant("(b)", (bool(above),)),
            None,
            Gio.DBusCallFlags.NO_AUTO_START,
            CALL_TIMEOUT,
            None,
        )
    except GLib.Error as exc:
        return exc.message
    return ""


def watch_service(on_change: Callable[[bool], None]) -> int:
    """Avisa quando a extensão entra ou sai do ar.

    Isso acontece em situações normais: o usuário liga ou desliga a extensão,
    o GNOME Shell reinicia. Sem observar, o daemon ficaria preso ao backend
    que existia no instante em que subiu.
    """
    return Gio.bus_watch_name(
        Gio.BusType.SESSION,
        BUS_NAME,
        Gio.BusNameWatcherFlags.NONE,
        lambda *_args: on_change(True),
        lambda *_args: on_change(False),
    )


def unwatch_service(watcher_id: int) -> None:
    if watcher_id:
        Gio.bus_unwatch_name(watcher_id)


def missing_hint() -> str:
    """Como resolver, curto o bastante para caber no banner da janela."""
    if not is_installed():
        return "a extensão do GNOME Shell do ArchClip não está instalada (rode ./install.sh)"
    # Instalada mas fora do ar quase sempre significa que o Shell ainda não a
    # carregou -- ele só faz isso no início da sessão.
    return "a extensão do ArchClip não está ativa — faça logout/login"
