"""Janela de configurações."""

from __future__ import annotations

import threading
from typing import Callable, Optional

from .. import __version__
from ..gtkdeps import Adw, Gdk, GLib, Gtk
from .. import autostart, updater
from ..hotkey import GnomeHotkeyBackend, accel_label, is_valid_accel, launcher_command

# Teclas que só fazem sentido combinadas: pressioná-las sozinhas não fecha a
# captura de atalho.
MODIFIER_KEYVALS = {
    Gdk.KEY_Shift_L, Gdk.KEY_Shift_R,
    Gdk.KEY_Control_L, Gdk.KEY_Control_R,
    Gdk.KEY_Alt_L, Gdk.KEY_Alt_R,
    Gdk.KEY_Super_L, Gdk.KEY_Super_R,
    Gdk.KEY_Meta_L, Gdk.KEY_Meta_R,
    Gdk.KEY_Hyper_L, Gdk.KEY_Hyper_R,
    Gdk.KEY_ISO_Level3_Shift, Gdk.KEY_Caps_Lock, Gdk.KEY_Num_Lock,
}


class ShortcutDialog(Adw.Window):
    """Captura a próxima combinação de teclas digitada pelo usuário."""

    def __init__(self, parent: Gtk.Window, on_captured: Callable[[str], None]) -> None:
        super().__init__(transient_for=parent, modal=True, title="Definir atalho")
        self.on_captured = on_captured
        self.set_default_size(400, 220)

        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar(show_end_title_buttons=False))
        self.set_content(view)

        status = Adw.StatusPage()
        status.set_icon_name("preferences-desktop-keyboard-shortcuts-symbolic")
        status.set_title("Pressione a combinação")
        status.set_description(
            "Use ao menos um modificador (Super, Ctrl ou Alt).\n"
            "Esc cancela."
        )
        view.set_content(status)
        self._status = status

        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(controller)

        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)

    def _on_map(self, *_args) -> None:
        """Pede ao compositor para não engolir os atalhos do sistema.

        Sem isso o Super+V seria interceptado pelo GNOME e nunca chegaria
        até aqui — exatamente o atalho que queremos capturar.
        """
        surface = self.get_surface()
        if surface is not None and hasattr(surface, "inhibit_system_shortcuts"):
            surface.inhibit_system_shortcuts(None)

    def _on_unmap(self, *_args) -> None:
        surface = self.get_surface()
        if surface is not None and hasattr(surface, "restore_system_shortcuts"):
            surface.restore_system_shortcuts()

    def _on_key_pressed(self, _controller, keyval, _keycode, state) -> bool:
        mods = state & Gtk.accelerator_get_default_mod_mask()

        if keyval in MODIFIER_KEYVALS:
            return True
        if keyval == Gdk.KEY_Escape and not mods:
            self.close()
            return True

        accel = Gtk.accelerator_name(Gdk.keyval_to_lower(keyval), mods)
        if not is_valid_accel(accel):
            self._status.set_description(
                "“{}” não serve como atalho global.\n"
                "Combine com Super, Ctrl ou Alt.".format(accel_label(accel))
            )
            return True

        self.on_captured(accel)
        self.close()
        return True


class SettingsWindow(Adw.PreferencesWindow):
    """Preferências do ArchClip."""

    def __init__(self, app) -> None:
        super().__init__(transient_for=app.window, modal=False)
        self.app = app
        self.config = app.config
        self.set_title("Configurações do ArchClip")
        self.set_default_size(560, 680)
        self.set_search_enabled(True)

        self.add(self._page_general())
        self.add(self._page_shortcut())
        self.add(self._page_system())
        self.add(self._page_privacy())

    # ---------------------------------------------------------------- helpers

    def _switch(self, title: str, subtitle: str, key: str) -> Adw.SwitchRow:
        row = Adw.SwitchRow(title=title, subtitle=subtitle)
        row.set_active(bool(self.config.get(key)))
        row.connect("notify::active", lambda r, _p: self.config.set(key, r.get_active()))
        return row

    def _spin(
        self, title: str, subtitle: str, key: str, lower: int, upper: int, step: int = 1
    ) -> Adw.SpinRow:
        adjustment = Gtk.Adjustment(
            value=float(self.config.get(key)),
            lower=lower,
            upper=upper,
            step_increment=step,
            page_increment=step * 5,
        )
        row = Adw.SpinRow(title=title, subtitle=subtitle, adjustment=adjustment)
        row.connect("notify::value", lambda r, _p: self.config.set(key, int(r.get_value())))
        return row

    @staticmethod
    def _button_row(title: str, subtitle: str, label: str, callback, destructive=False):
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        button = Gtk.Button(label=label)
        button.set_valign(Gtk.Align.CENTER)
        button.add_css_class("destructive-action" if destructive else "flat")
        button.connect("clicked", callback)
        row.add_suffix(button)
        row.set_activatable_widget(button)
        return row, button

    # ------------------------------------------------------------------ geral

    def _page_general(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Geral", icon_name="preferences-system-symbolic")

        history = Adw.PreferencesGroup(
            title="Histórico",
            description="Itens fixados nunca são descartados pelo limite.",
        )
        history.add(
            self._spin(
                "Itens no histórico",
                "Quantos itens não fixados manter",
                "max_items",
                5,
                500,
                5,
            )
        )
        history.add(self._switch("Capturar texto", "Guardar textos copiados", "capture_text"))
        history.add(
            self._switch("Capturar imagens", "Guardar prints e imagens copiadas", "capture_images")
        )
        history.add(
            self._spin(
                "Tamanho máximo por item (MB)",
                "Conteúdos maiores são ignorados",
                "max_item_size_mb",
                1,
                256,
            )
        )
        page.add(history)

        window = Adw.PreferencesGroup(title="Janela")
        window.add(
            self._switch(
                "Fechar ao escolher um item",
                "Some assim que o item vai para a área de transferência",
                "close_on_copy",
            )
        )
        self._focus_row = self._switch(
            "Fechar ao perder o foco",
            "Comportamento igual ao do Win+V",
            "close_on_focus_loss",
        )
        window.add(self._focus_row)

        self._on_top_row = self._switch(
            "Manter sempre visível",
            "A janela fica por cima das outras: dá para usar o resto da tela "
            "sem perder o histórico de vista",
            "keep_on_top",
        )
        self._on_top_row.connect("notify::active", lambda *_: self._on_keep_on_top())
        if not self.app.keep_on_top_available():
            # No Wayland, empilhamento é decisão do compositor: sem a extensão
            # do Shell não existe como um app comum se pôr acima dos outros.
            self._on_top_row.set_sensitive(False)
            self._on_top_row.set_subtitle(
                "Indisponível: a extensão do GNOME Shell não está no ar ou é "
                "de uma versão anterior — faça logout/login"
            )
        window.add(self._on_top_row)
        self._sync_window_rows()

        paste_row = self._switch(
            "Colar automaticamente",
            "Envia Ctrl+V para a janela ativa (requer ydotool ou wtype)",
            "auto_paste",
        )
        if not self.app.auto_paste_tool():
            paste_row.set_sensitive(False)
            paste_row.set_subtitle("Indisponível: instale ydotool (sudo pacman -S ydotool)")
        window.add(paste_row)
        page.add(window)

        return page

    def _on_keep_on_top(self) -> None:
        error = self.app.apply_keep_on_top()
        self._sync_window_rows()
        if error:
            self._toast("Não consegui falar com a extensão do Shell: {}".format(error))

    def _sync_window_rows(self) -> None:
        """Enquanto a janela fica sempre visível, fechar ao perder o foco não
        faz sentido -- seria fechar justamente quando você vai usar a tela."""
        fixa = bool(self.config.get("keep_on_top"))
        self._focus_row.set_sensitive(not fixa)
        self._focus_row.set_subtitle(
            "Ignorado enquanto a janela fica sempre visível"
            if fixa
            else "Comportamento igual ao do Win+V"
        )

    # ----------------------------------------------------------------- atalho

    def _page_shortcut(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(
            title="Atalho", icon_name="preferences-desktop-keyboard-shortcuts-symbolic"
        )

        group = Adw.PreferencesGroup(
            title="Atalho global",
            description=(
                "No Wayland quem registra atalhos é o compositor. O ArchClip grava "
                "um atalho personalizado no GNOME e libera a combinação de quem "
                "já a usava."
            ),
        )

        self._shortcut_row = Adw.ActionRow(title="Abrir a área de transferência")
        self._shortcut_label = Gtk.Label()
        self._shortcut_label.add_css_class("dim-label")
        self._shortcut_row.add_suffix(self._shortcut_label)

        change = Gtk.Button(label="Alterar")
        change.set_valign(Gtk.Align.CENTER)
        change.connect("clicked", self._on_change_shortcut)
        self._shortcut_row.add_suffix(change)
        self._shortcut_row.set_activatable_widget(change)
        group.add(self._shortcut_row)

        enabled = self._switch(
            "Atalho ativo",
            "Desligue para devolver a combinação ao sistema",
            "hotkey_enabled",
        )
        enabled.connect("notify::active", lambda *_: self._reapply_hotkey())
        group.add(enabled)
        page.add(group)

        self._conflict_group = Adw.PreferencesGroup(title="Atalhos do sistema substituídos")
        self._conflict_rows: list[Gtk.Widget] = []
        restore_row, _ = self._button_row(
            "Restaurar atalhos originais",
            "Devolve as combinações que o ArchClip tomou do GNOME",
            "Restaurar",
            self._on_restore_conflicts,
        )
        self._restore_row = restore_row
        self._conflict_group.add(restore_row)
        page.add(self._conflict_group)

        manual = Adw.PreferencesGroup(
            title="Registro manual",
            description=(
                "Se o seu ambiente não for GNOME, registre este comando no atalho "
                "que preferir:"
            ),
        )
        command_row = Adw.ActionRow(title=launcher_command("--toggle"))
        command_row.set_subtitle("Comando executado pelo atalho")
        command_row.add_css_class("property")
        copy_button = Gtk.Button(icon_name="edit-copy-symbolic")
        copy_button.set_valign(Gtk.Align.CENTER)
        copy_button.add_css_class("flat")
        copy_button.set_tooltip_text("Copiar comando")
        copy_button.connect("clicked", self._on_copy_command)
        command_row.add_suffix(copy_button)
        manual.add(command_row)
        page.add(manual)

        self._refresh_shortcut_ui()
        return page

    def _refresh_shortcut_ui(self) -> None:
        accel = self.config.get("hotkey")
        self._shortcut_label.set_label(accel_label(accel))

        for row in self._conflict_rows:
            self._conflict_group.remove(row)
        self._conflict_rows.clear()

        overridden = self.config.get("overridden_bindings") or {}
        for marker, values in overridden.items():
            schema, _, key = marker.rpartition(":")
            row = Adw.ActionRow(title=key.replace("-", " ").capitalize())
            row.set_subtitle("{} — original: {}".format(schema, ", ".join(values) or "vazio"))
            self._conflict_group.add(row)
            self._conflict_rows.append(row)

        has_conflicts = bool(overridden)
        self._restore_row.set_sensitive(has_conflicts)
        self._conflict_group.set_description(
            "Nenhum atalho do sistema foi alterado."
            if not has_conflicts
            else "O ArchClip removeu estas combinações para poder usá-las."
        )

    def _on_change_shortcut(self, _button) -> None:
        ShortcutDialog(self, self._apply_new_shortcut).present()

    def _apply_new_shortcut(self, accel: str) -> None:
        self.config.set("hotkey", accel)
        self.config.set("hotkey_enabled", True)
        self._reapply_hotkey()

    def _reapply_hotkey(self) -> None:
        error = self.app.apply_hotkey()
        self._refresh_shortcut_ui()
        if error:
            self._toast(error)
        else:
            self._toast("Atalho {} registrado.".format(accel_label(self.config.get("hotkey"))))

    def _on_restore_conflicts(self, _button) -> None:
        backend = self.app.hotkey_backend
        if isinstance(backend, GnomeHotkeyBackend):
            backend.restore_conflicts()
            self._refresh_shortcut_ui()
            self._toast("Atalhos do sistema restaurados.")

    def _on_copy_command(self, _button) -> None:
        if self.app.copy_text(launcher_command("--toggle")):
            self._toast("Comando copiado.")
        else:
            self._toast("Não consegui acessar a área de transferência.")

    # ---------------------------------------------------------------- sistema

    def _page_system(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Sistema", icon_name="application-x-executable-symbolic")

        startup = Adw.PreferencesGroup(title="Inicialização")
        self._autostart_row = Adw.SwitchRow(
            title="Iniciar com o sistema",
            subtitle="Mantém o histórico ativo desde o login",
        )
        self._autostart_row.set_active(autostart.is_enabled())
        self._autostart_row.connect("notify::active", self._on_autostart_toggled)
        startup.add(self._autostart_row)
        page.add(startup)

        updates = Adw.PreferencesGroup(
            title="Atualizações",
            description="Versão instalada: {}".format(__version__),
        )
        updates.add(
            self._switch(
                "Procurar atualizações",
                "Consulta as releases do GitHub uma vez por dia",
                "update_check",
            )
        )

        auto_row = self._switch(
            "Instalar automaticamente",
            "Baixa e aplica a nova versão sem perguntar",
            "update_auto_install",
        )
        reason = updater.why_not_self_install()
        if reason:
            auto_row.set_sensitive(False)
            auto_row.set_subtitle(reason)
        updates.add(auto_row)

        check_row, self._check_button = self._button_row(
            "Verificar agora",
            "Consulta a release mais recente",
            "Verificar",
            self._on_check_updates,
        )
        self._check_row = check_row
        updates.add(check_row)
        page.add(updates)

        return page

    def _on_autostart_toggled(self, row, _param) -> None:
        error = autostart.set_enabled(row.get_active())
        self.config.set("autostart", row.get_active())
        if error:
            self._toast("Falha no autostart: {}".format(error))

    def _on_check_updates(self, _button) -> None:
        self._check_button.set_sensitive(False)
        self._check_row.set_subtitle("Consultando o GitHub…")

        def work() -> None:
            release, error = updater.check()
            GLib.idle_add(self._on_check_done, release, error)

        threading.Thread(target=work, daemon=True).start()

    def _on_check_done(self, release: Optional[updater.Release], error: str) -> bool:
        self._check_button.set_sensitive(True)
        if error:
            self._check_row.set_subtitle(error)
        elif release is None:
            self._check_row.set_subtitle("Você já está na versão mais recente.")
        else:
            self._check_row.set_subtitle("Disponível: versão {}".format(release.label))
            self.app.offer_update(release, parent=self)
        return GLib.SOURCE_REMOVE

    # ------------------------------------------------------------- privacidade

    def _page_privacy(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Privacidade", icon_name="channel-secure-symbolic")

        group = Adw.PreferencesGroup(title="Conteúdo sensível")
        group.add(
            self._switch(
                "Ignorar gerenciadores de senha",
                "Não guarda seleções marcadas como secretas (KeePassXC, Bitwarden…)",
                "ignore_password_managers",
            )
        )
        group.add(
            self._switch(
                "Limpar ao encerrar",
                "Apaga os itens não fixados quando o ArchClip fecha",
                "clear_on_exit",
            )
        )
        page.add(group)

        danger = Adw.PreferencesGroup(title="Dados")
        clear_row, _ = self._button_row(
            "Apagar todo o histórico",
            "Remove itens fixados, textos e imagens salvas",
            "Apagar tudo",
            self._on_clear_everything,
            destructive=True,
        )
        danger.add(clear_row)
        page.add(danger)

        return page

    def _on_clear_everything(self, _button) -> None:
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Apagar todo o histórico?",
            body="Todos os itens, inclusive os fixados, serão removidos. Não dá para desfazer.",
        )
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("clear", "Apagar tudo")
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_clear_everything_response)
        dialog.present()

    def _on_clear_everything_response(self, _dialog, response: str) -> None:
        if response != "clear":
            return
        removed = self.app.store.clear(keep_pinned=False)
        self.app.window.refresh()
        self._toast("{} itens removidos.".format(removed))

    # ------------------------------------------------------------------ toast

    def _toast(self, message: str) -> None:
        self.add_toast(Adw.Toast(title=message, timeout=4))
