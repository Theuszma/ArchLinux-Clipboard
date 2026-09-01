"""Linha da lista que representa um item do histórico."""

from __future__ import annotations

from typing import Callable, Optional

from ..gtkdeps import Gdk, GdkPixbuf, GLib, Gtk, Pango
from ..storage import Item
from ..util import DIR_MODE, FILE_MODE, THUMB_DIR, elide, harden, human_size, human_time

THUMB_WIDTH = 96
THUMB_HEIGHT = 64


def thumbnail(item: Item) -> Optional[Gdk.Texture]:
    """Miniatura da imagem, gerada uma vez e cacheada em disco."""
    if not item.blob_path:
        return None
    cached = THUMB_DIR / (item.hash + ".png")
    if not cached.is_file():
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                item.blob_path, THUMB_WIDTH, THUMB_HEIGHT, True
            )
            THUMB_DIR.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
            harden(THUMB_DIR, DIR_MODE)
            pixbuf.savev(str(cached), "png", [], [])
            # A miniatura de um print pode ser tão sensível quanto o original.
            harden(cached, FILE_MODE)
        except (GLib.Error, OSError):
            return None
    try:
        return Gdk.Texture.new_from_filename(str(cached))
    except GLib.Error:
        return None


def _looks_like_code(text: str) -> bool:
    """Heurística leve para exibir trechos de código em monoespaçada."""
    sample = text[:400]
    if "\n" in sample and sample.count("  ") > 2:
        return True
    markers = ("{", "};", "()", "=>", "def ", "function ", "import ", "#!/", "</")
    return sum(marker in sample for marker in markers) >= 2


class ItemRow(Gtk.ListBoxRow):
    """Uma entrada do histórico, com botões de fixar e apagar."""

    def __init__(
        self,
        item: Item,
        on_pin: Callable[[Item], None],
        on_delete: Callable[[Item], None],
    ) -> None:
        super().__init__()
        self.item = item
        self._on_pin = on_pin
        self._on_delete = on_delete

        self.add_css_class("clip-row")
        if item.pinned:
            self.add_css_class("pinned")
        self.set_tooltip_text(self._tooltip())

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.set_child(box)

        box.append(self._build_leading())
        box.append(self._build_body())
        box.append(self._build_actions())

    # ------------------------------------------------------------- construção

    def _build_leading(self) -> Gtk.Widget:
        if self.item.is_image:
            texture = thumbnail(self.item)
            if texture is not None:
                picture = Gtk.Picture.new_for_paintable(texture)
                picture.set_content_fit(Gtk.ContentFit.COVER)
                picture.set_size_request(THUMB_WIDTH, THUMB_HEIGHT)
                picture.add_css_class("clip-thumb")
                picture.set_valign(Gtk.Align.CENTER)
                return picture
            icon_name = "image-missing-symbolic"
        else:
            icon_name = "text-x-generic-symbolic"

        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(24)
        icon.set_valign(Gtk.Align.START)
        icon.set_margin_top(4)
        icon.add_css_class("dim-label")
        return icon

    def _build_body(self) -> Gtk.Widget:
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        body.set_hexpand(True)
        body.set_valign(Gtk.Align.CENTER)

        preview = Gtk.Label(label=self._preview_text())
        preview.set_xalign(0)
        preview.set_wrap(True)
        preview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        preview.set_lines(2)
        preview.set_ellipsize(Pango.EllipsizeMode.END)
        preview.add_css_class("clip-preview")
        if not self.item.is_image and _looks_like_code(self.item.text or ""):
            preview.add_css_class("monospace")
        body.append(preview)

        meta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        if self.item.pinned:
            badge = Gtk.Label(label="FIXADO")
            badge.add_css_class("clip-badge")
            meta.append(badge)

        detail = Gtk.Label(label=self._meta_text())
        detail.set_xalign(0)
        detail.add_css_class("clip-meta")
        meta.append(detail)
        body.append(meta)

        return body

    def _build_actions(self) -> Gtk.Widget:
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        actions.set_valign(Gtk.Align.CENTER)
        actions.add_css_class("clip-actions")

        pin = Gtk.Button()
        pin.set_icon_name("view-pin-symbolic")
        pin.set_tooltip_text("Desafixar" if self.item.pinned else "Fixar no topo")
        pin.add_css_class("flat")
        if self.item.pinned:
            pin.add_css_class("clip-pin-active")
        pin.connect("clicked", lambda _button: self._on_pin(self.item))
        actions.append(pin)

        delete = Gtk.Button()
        delete.set_icon_name("user-trash-symbolic")
        delete.set_tooltip_text("Remover do histórico")
        delete.add_css_class("flat")
        delete.connect("clicked", lambda _button: self._on_delete(self.item))
        actions.append(delete)

        return actions

    # ----------------------------------------------------------------- textos

    def _preview_text(self) -> str:
        if self.item.is_image:
            if self.item.width and self.item.height:
                return "Imagem {}x{}".format(self.item.width, self.item.height)
            return "Imagem"
        return elide(self.item.text or self.item.preview, 220)

    def _meta_text(self) -> str:
        parts = [human_time(self.item.updated_at)]
        if self.item.is_image:
            parts.append(human_size(self.item.size))
            parts.append(self.item.mime.split("/")[-1].upper())
        else:
            lines = (self.item.text or "").count("\n") + 1
            chars = len(self.item.text or "")
            parts.append("{} caracteres".format(chars) if lines == 1 else "{} linhas".format(lines))
        return " · ".join(parts)

    def _tooltip(self) -> str:
        if self.item.is_image:
            return "Imagem {} · {}".format(self.item.mime, human_size(self.item.size))
        return elide(self.item.text or "", 600)
