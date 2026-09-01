"""Ponto único de `gi.require_version`.

Todo módulo que precisa de GTK importa daqui em vez de `gi.repository`, o que
garante que as versões sejam fixadas antes do primeiro import de verdade.
"""

from __future__ import annotations

import sys

try:
    import gi
except ImportError:  # pragma: no cover - depende do ambiente
    sys.exit(
        "archclip: PyGObject não encontrado.\n"
        "Instale com: sudo pacman -S python-gobject gtk4 libadwaita"
    )

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Pango", "1.0")

from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango  # noqa: E402

__all__ = ["Adw", "Gdk", "GdkPixbuf", "Gio", "GLib", "Gtk", "Pango"]
