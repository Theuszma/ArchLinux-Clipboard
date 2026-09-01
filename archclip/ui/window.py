"""Janela pop-up do histórico — o equivalente ao Win+V."""

from __future__ import annotations

from typing import Optional

from .. import APP_NAME
from ..gtkdeps import Adw, Gdk, Gio, GLib, Gtk
from ..hotkey import accel_label
from ..storage import Item
from .rows import ItemRow

FILTERS = (
    ("all", "Tudo", None),
    ("pinned", "Fixados", None),
    ("text", "Texto", "text"),
    ("image", "Imagens", "image"),
)


class ClipboardWindow(Adw.ApplicationWindow):
    """Lista o histórico do mais recente ao mais antigo, fixados no topo."""

    def __init__(self, app) -> None:
        super().__init__(application=app, title=APP_NAME)
        self.app = app
        self.filter_key = "all"

        self.set_default_size(460, 580)
        # Fechar apenas esconde: o daemon continua vigiando o clipboard.
        self.set_hide_on_close(True)

        self._build_ui()
        self._install_shortcuts()

        self.connect("notify::is-active", self._on_active_changed)

    # ------------------------------------------------------------- construção

    def _build_ui(self) -> None:
        view = Adw.ToolbarView()
        self.set_content(view)

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=APP_NAME))
        header.pack_end(self._build_menu_button())
        view.add_top_bar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        view.set_content(content)

        self.banner = Adw.Banner()
        self.banner.set_revealed(False)
        self.banner.set_button_label("Dispensar")
        self.banner.connect("button-clicked", lambda _b: self.banner.set_revealed(False))
        content.append(self.banner)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Buscar no histórico…")
        self.search.set_margin_start(12)
        self.search.set_margin_end(12)
        self.search.set_margin_top(6)
        self.search.set_margin_bottom(8)
        self.search.connect("search-changed", lambda _entry: self.refresh())
        # Digitar em qualquer lugar da janela começa a busca.
        self.search.set_key_capture_widget(self)
        content.append(self.search)

        content.append(self._build_filters())

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.BROWSE)
        self.list_box.add_css_class("clip-list")
        self.list_box.connect("row-activated", self._on_row_activated)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(self.list_box)

        self.empty = Adw.StatusPage()
        self.empty.set_icon_name("edit-paste-symbolic")
        self.empty.set_title("Histórico vazio")
        self.empty.set_description("Copie algo e o item aparecerá aqui.")

        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        self.stack.add_named(scroller, "list")
        self.stack.add_named(self.empty, "empty")
        content.append(self.stack)

        self.footer = Gtk.Label()
        self.footer.set_xalign(0)
        self.footer.add_css_class("clip-footer")
        content.append(self.footer)

    def _build_filters(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        box.add_css_class("linked")
        box.add_css_class("clip-filters")
        box.set_halign(Gtk.Align.CENTER)

        self._filter_buttons: dict[str, Gtk.ToggleButton] = {}
        first: Optional[Gtk.ToggleButton] = None
        for key, label, _kind in FILTERS:
            button = Gtk.ToggleButton(label=label)
            if first is None:
                first = button
                button.set_active(True)
            else:
                button.set_group(first)
            button.connect("toggled", self._on_filter_toggled, key)
            self._filter_buttons[key] = button
            box.append(button)
        return box

    def _build_menu_button(self) -> Gtk.Widget:
        menu = Gio.Menu()

        capture = Gio.Menu()
        # Escape rápido para copiar algo sensível sem deixar rastro.
        capture.append("Pausar captura", "app.pause")
        menu.append_section(None, capture)

        history = Gio.Menu()
        history.append("Limpar não fixados", "win.clear-unpinned")
        history.append("Limpar tudo", "win.clear-all")
        menu.append_section(None, history)

        rest = Gio.Menu()
        rest.append("Configurações", "app.settings")
        rest.append("Sobre", "app.about")
        rest.append("Encerrar o ArchClip", "app.quit-app")
        menu.append_section(None, rest)

        button = Gtk.MenuButton()
        button.set_icon_name("open-menu-symbolic")
        button.set_menu_model(menu)
        button.set_tooltip_text("Menu")
        return button

    # ------------------------------------------------------------- atalhos

    def _install_shortcuts(self) -> None:
        for name, callback in (
            ("clear-unpinned", lambda *_: self._confirm_clear(keep_pinned=True)),
            ("clear-all", lambda *_: self._confirm_clear(keep_pinned=False)),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key_capture)
        self.add_controller(keys)

        bubble = Gtk.EventControllerKey()
        bubble.connect("key-pressed", self._on_key_bubble)
        self.add_controller(bubble)

    def _on_key_capture(self, _controller, keyval, _keycode, _state) -> bool:
        if keyval == Gdk.KEY_Escape:
            # Primeiro Esc limpa a busca; o seguinte fecha a janela.
            if self.search.get_text():
                self.search.set_text("")
            else:
                self.close()
            return True
        return False

    def _on_key_bubble(self, _controller, keyval, _keycode, state) -> bool:
        row = self.list_box.get_selected_row()
        if row is None or not isinstance(row, ItemRow):
            return False

        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if keyval == Gdk.KEY_Delete and not isinstance(self.get_focus(), Gtk.Text):
            self.on_delete(row.item)
            return True
        if ctrl and keyval in (Gdk.KEY_p, Gdk.KEY_P):
            self.on_pin(row.item)
            return True
        return False

    # ------------------------------------------------------------- conteúdo

    def refresh(self, reset_selection: bool = False) -> None:
        """Recarrega a lista a partir do banco, respeitando busca e filtro."""
        # Uma captura nova chega enquanto a janela está aberta; sem isto, a
        # linha em que o usuário estava navegando saltaria para o topo.
        previous = None
        if not reset_selection:
            selected = self.list_box.get_selected_row()
            if isinstance(selected, ItemRow):
                previous = selected.item.id

        kind = None
        pinned_only = False
        for key, _label, filter_kind in FILTERS:
            if key == self.filter_key:
                kind = filter_kind
                pinned_only = key == "pinned"

        items = self.app.store.list(
            query=self.search.get_text(),
            kind=kind,
            pinned_only=pinned_only,
        )

        self.list_box.remove_all()
        restored = None
        for item in items:
            row = ItemRow(item, self.on_pin, self.on_delete)
            self.list_box.append(row)
            if previous is not None and item.id == previous:
                restored = row

        if items:
            self.stack.set_visible_child_name("list")
            target = restored or self.list_box.get_row_at_index(0)
            if target is not None:
                self.list_box.select_row(target)
        else:
            self.stack.set_visible_child_name("empty")
            self._update_empty_state()

        self._update_footer(len(items))

    def _update_empty_state(self) -> None:
        if self.search.get_text():
            self.empty.set_icon_name("system-search-symbolic")
            self.empty.set_title("Nada encontrado")
            self.empty.set_description("Nenhum item corresponde à busca.")
        elif self.filter_key == "pinned":
            self.empty.set_icon_name("view-pin-symbolic")
            self.empty.set_title("Nenhum item fixado")
            self.empty.set_description("Use o alfinete para manter um item no topo.")
        else:
            self.empty.set_icon_name("edit-paste-symbolic")
            self.empty.set_title("Histórico vazio")
            self.empty.set_description("Copie algo e o item aparecerá aqui.")

    def _update_footer(self, shown: int) -> None:
        total, pinned = self.app.store.count()
        limit = self.app.config.get("max_items")
        accel = self.app.config.get("hotkey")
        parts = ["{} de {} itens".format(shown, total)]
        if pinned:
            parts.append("{} fixado(s)".format(pinned))
        parts.append("limite {}".format(limit))
        if self.app.config.get("hotkey_enabled"):
            parts.append(accel_label(accel))
        self.footer.set_label(" · ".join(parts))

    def show_banner(self, message: str) -> None:
        if message:
            self.banner.set_title(message)
            self.banner.set_revealed(True)
        else:
            self.banner.set_revealed(False)

    # --------------------------------------------------------------- ações

    def _on_filter_toggled(self, button: Gtk.ToggleButton, key: str) -> None:
        if button.get_active():
            self.filter_key = key
            self.refresh()

    def _on_row_activated(self, _list_box, row) -> None:
        if isinstance(row, ItemRow):
            self.app.copy_item(row.item)

    def on_pin(self, item: Item) -> None:
        self.app.store.toggle_pin(item.id)
        self.refresh()

    def on_delete(self, item: Item) -> None:
        self.app.store.delete(item.id)
        self.refresh()

    def _confirm_clear(self, keep_pinned: bool) -> None:
        title = "Limpar itens não fixados?" if keep_pinned else "Limpar todo o histórico?"
        body = (
            "Os itens fixados serão mantidos."
            if keep_pinned
            else "Isso também remove os itens fixados. Não dá para desfazer."
        )
        dialog = Adw.MessageDialog(transient_for=self, heading=title, body=body)
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("clear", "Limpar")
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_clear_response, keep_pinned)
        dialog.present()

    def _on_clear_response(self, _dialog, response: str, keep_pinned: bool) -> None:
        if response == "clear":
            self.app.store.clear(keep_pinned=keep_pinned)
            self.refresh()

    # ------------------------------------------------------------ visibilidade

    def _on_active_changed(self, *_args) -> None:
        """Some ao perder o foco, como a área de transferência do Windows."""
        if self.get_property("is-active"):
            return
        if not self.app.config.get("close_on_focus_loss"):
            return
        if not self.get_visible():
            return
        # Espera um instante: diálogos filhos também tiram o foco da janela.
        GLib.timeout_add(150, self._hide_if_still_inactive)

    def _hide_if_still_inactive(self) -> bool:
        if not self.get_property("is-active") and not self._has_modal_child():
            self.set_visible(False)
        return GLib.SOURCE_REMOVE

    def _has_modal_child(self) -> bool:
        application = self.get_application()
        if application is None:
            return False
        return any(
            window.get_visible() and window.get_transient_for() is self
            for window in application.get_windows()
        )

    def present_fresh(self) -> None:
        """Abre a janela já limpa e pronta para navegar pelo teclado."""
        self.search.set_text("")
        self.refresh(reset_selection=True)
        self.present()
        self.list_box.grab_focus()
