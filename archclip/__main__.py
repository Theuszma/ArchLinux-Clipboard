"""Ponto de entrada do ArchClip."""

from __future__ import annotations

import sys

from . import APP_ID, __version__

OBJECT_PATH = "/" + APP_ID.replace(".", "/")


def _fast_toggle() -> bool:
    """Aciona a ação `toggle` no daemon já em execução, via D-Bus.

    O atalho global dispara este processo a cada tecla, então vale evitar o
    custo de carregar GTK e libadwaita quando o daemon já está de pé: aqui só
    o GIO é importado. Retorna False se não houver daemon rodando, e aí o
    caminho normal (que sobe a aplicação inteira) assume.
    """
    try:
        from gi.repository import Gio, GLib
    except ImportError:
        return False

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync(
            APP_ID,
            OBJECT_PATH,
            "org.gtk.Actions",
            "Activate",
            GLib.Variant("(sava{sv})", ("toggle", [], {})),
            None,
            Gio.DBusCallFlags.NO_AUTO_START,
            1500,
            None,
        )
        return True
    except GLib.Error:
        return False


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)

    if "--version" in argv or "-V" in argv:
        print("ArchClip {}".format(__version__))
        return 0

    if "--toggle" in argv and _fast_toggle():
        return 0

    from .app import ArchClipApp

    return ArchClipApp().run(argv)


if __name__ == "__main__":
    sys.exit(main())
