"""Aplicação GTK: daemon do clipboard + janela do histórico."""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from . import APP_ID, APP_NAME, GITHUB_REPO, __version__
from . import autostart, updater
from .clipboard import detect_backend
from .config import Config
from .gtkdeps import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk
from .hotkey import GnomeHotkeyBackend, accel_label
from .hotkey import detect_backend as detect_hotkey_backend
from .monitor import Monitor
from .storage import Item, Store
from .ui.settings import SettingsWindow
from .ui.window import ClipboardWindow
from .util import ensure_dirs

# Envia Ctrl+V para a janela em foco. O Wayland não deixa um app comum
# sintetizar teclas, então dependemos de uma ferramenta externa.
AUTO_PASTE_TOOLS = (
    ("ydotool", ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"]),
    ("wtype", ["wtype", "-M", "ctrl", "v", "-m", "ctrl"]),
)

UPDATE_CHECK_DELAY = 30  # segundos após o início
AUTO_PASTE_DELAY = 180  # ms, para o foco voltar ao app anterior


class ArchClipApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.config = Config()
        self.store: Optional[Store] = None
        self.monitor: Optional[Monitor] = None
        self.window: Optional[ClipboardWindow] = None
        self.settings_window: Optional[SettingsWindow] = None
        self.hotkey_backend = None
        self.clipboard_backend = None
        self.startup_message = ""
        self.monitor_error = ""
        # Pausa é de propósito só da sessão: um histórico que continua
        # pausado depois do reboot, em silêncio, é armadilha.
        self.paused = False

        self._add_cli_options()

    # ------------------------------------------------------------------- CLI

    def _add_cli_options(self) -> None:
        options = (
            ("daemon", "Roda em segundo plano sem abrir a janela"),
            ("toggle", "Abre ou fecha a janela do histórico"),
            ("show", "Abre a janela do histórico"),
            ("settings", "Abre as configurações"),
            ("quit", "Encerra o daemon do ArchClip"),
            ("check-updates", "Procura atualizações imediatamente"),
        )
        for name, description in options:
            self.add_main_option(
                name, 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE, description, None
            )

    def do_command_line(self, command_line) -> int:
        options = command_line.get_options_dict().end().unpack()

        if "quit" in options:
            self.quit()
            return 0
        if "check-updates" in options:
            self._check_updates(manual=True)
            return 0
        if "settings" in options:
            self._show_settings()
            return 0
        if "toggle" in options:
            self._toggle_window()
            return 0
        if "show" in options:
            self._show_window()
            return 0
        if "daemon" in options:
            return 0  # o daemon já subiu em do_startup

        # Sem argumentos: primeira execução mostra a janela.
        self._show_window()
        return 0

    # -------------------------------------------------------------- ciclo de vida

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        ensure_dirs()

        # Mantém o processo vivo mesmo sem janela aberta: somos um daemon.
        self.hold()

        self._load_css()
        self.store = Store()
        self.store.trim(int(self.config.get("max_items")))

        backend, error = detect_backend()
        self.startup_message = error
        if backend is not None:
            self.monitor = Monitor(
                self.config, backend, self._on_capture, self._on_monitor_status
            )
            self.monitor.start()
        self.clipboard_backend = backend

        self.hotkey_backend = detect_hotkey_backend(self.config)
        self.window = ClipboardWindow(self)
        self._register_actions()

        if self.config.get("hotkey_enabled"):
            hotkey_error = self.apply_hotkey()
            if hotkey_error and not self.startup_message:
                self.startup_message = hotkey_error

        if self.config.get("autostart") and not autostart.is_enabled():
            autostart.set_enabled(True)
        else:
            autostart.refresh()

        self.config.connect(self._on_config_changed)
        self._refresh_status()

        GLib.timeout_add_seconds(UPDATE_CHECK_DELAY, self._maybe_check_updates)

    def do_shutdown(self) -> None:
        if self.monitor is not None:
            self.monitor.stop()
        if self.store is not None:
            if self.config.get("clear_on_exit"):
                self.store.clear(keep_pinned=True)
            self.store.close()
        Adw.Application.do_shutdown(self)

    def _load_css(self) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        provider = Gtk.CssProvider()
        provider.load_from_path(str(Path(__file__).parent / "ui" / "style.css"))
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    # ----------------------------------------------------------------- ações

    def _register_actions(self) -> None:
        actions = (
            ("toggle", lambda *_: self._toggle_window()),
            ("show", lambda *_: self._show_window()),
            ("settings", lambda *_: self._show_settings()),
            ("about", lambda *_: self._show_about()),
            ("quit-app", lambda *_: self.quit()),
        )
        for name, callback in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        # Ação com estado booleano: o menu a desenha como caixa de seleção e
        # o próprio GIO alterna o estado ao ativá-la.
        pause = Gio.SimpleAction.new_stateful("pause", None, GLib.Variant.new_boolean(False))
        pause.connect("change-state", self._on_pause_change_state)
        self.add_action(pause)

        self.set_accels_for_action("app.settings", ["<Control>comma"])
        self.set_accels_for_action("app.quit-app", ["<Control>q"])
        self.set_accels_for_action("app.pause", ["<Control>space"])

    def _on_pause_change_state(self, action, value) -> None:
        action.set_state(value)
        self.paused = value.get_boolean()
        if self.monitor is not None:
            self.monitor.paused = self.paused
        self._refresh_status()

    def _on_monitor_status(self, message: str) -> bool:
        self.monitor_error = message
        self._refresh_status()
        return GLib.SOURCE_REMOVE

    def _refresh_status(self) -> None:
        """Mostra na janela o problema mais relevante, se houver algum."""
        if self.window is None:
            return
        if self.startup_message:
            message = self.startup_message
        elif self.paused:
            message = "Captura pausada — nada novo está sendo guardado."
        elif self.monitor_error:
            message = "Não estou vigiando a área de transferência: {}".format(
                self.monitor_error
            )
        else:
            message = ""
        self.window.show_banner(message)

    def _toggle_window(self) -> None:
        if self.window is None:
            return
        if self.window.get_visible() and self.window.get_property("is-active"):
            self.window.set_visible(False)
        else:
            self.window.present_fresh()

    def _show_window(self) -> None:
        if self.window is not None:
            self.window.present_fresh()

    def _show_settings(self) -> None:
        if self.settings_window is None:
            self.settings_window = SettingsWindow(self)
            self.settings_window.connect("close-request", self._on_settings_closed)
        self.settings_window.present()

    def _on_settings_closed(self, *_args) -> bool:
        self.settings_window = None
        return False

    def _show_about(self) -> None:
        about = Adw.AboutWindow(
            transient_for=self.window,
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=__version__,
            developer_name="Theuszma",
            comments=(
                "Histórico da área de transferência para Arch Linux, "
                "com a usabilidade do Win+V."
            ),
            website="https://github.com/{}".format(GITHUB_REPO),
            issue_url="https://github.com/{}/issues".format(GITHUB_REPO),
            license_type=Gtk.License.MIT_X11,
        )
        about.present()

    # -------------------------------------------------------------- captura

    def _on_capture(self, mime: str, data: bytes) -> bool:
        """Chamado na thread principal para cada mudança do clipboard."""
        if self.store is None:
            return GLib.SOURCE_REMOVE

        if mime.startswith("image/"):
            width, height = _image_dimensions(data)
            self.store.add_image(data, mime, width, height)
        else:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                return GLib.SOURCE_REMOVE
            self.store.add_text(text, mime)

        self.store.trim(int(self.config.get("max_items")))
        if self.window is not None and self.window.get_visible():
            self.window.refresh()
        return GLib.SOURCE_REMOVE

    # ----------------------------------------------------------------- colar

    def copy_item(self, item: Item) -> None:
        """Coloca o item de volta na área de transferência do sistema."""
        if self.clipboard_backend is None:
            return

        if item.is_image:
            if not item.blob_path:
                return
            try:
                data = Path(item.blob_path).read_bytes()
            except OSError as exc:
                self._notify_error("Não consegui ler a imagem: {}".format(exc))
                return
        else:
            data = (item.text or "").encode("utf-8")

        try:
            self.clipboard_backend.write(data, item.mime)
        except Exception as exc:  # subprocesso externo: qualquer falha é possível
            self._notify_error("Falha ao copiar: {}".format(exc))
            return

        # Evita que a nossa própria escrita volte como uma captura nova.
        if self.monitor is not None:
            self.monitor.note_own_write(data)

        if self.config.get("close_on_copy") and self.window is not None:
            self.window.set_visible(False)

        if self.config.get("auto_paste"):
            GLib.timeout_add(AUTO_PASTE_DELAY, self._send_paste)

    def copy_text(self, text: str) -> bool:
        """Coloca um texto solto no clipboard, sem passar pelo histórico."""
        if self.clipboard_backend is None:
            return False
        data = text.encode("utf-8")
        try:
            self.clipboard_backend.write(data, "text/plain;charset=utf-8")
        except Exception as exc:
            self._notify_error("Falha ao copiar: {}".format(exc))
            return False
        if self.monitor is not None:
            self.monitor.note_own_write(data)
        return True

    def auto_paste_tool(self) -> Optional[str]:
        for name, _command in AUTO_PASTE_TOOLS:
            if shutil.which(name):
                return name
        return None

    def _send_paste(self) -> bool:
        for name, command in AUTO_PASTE_TOOLS:
            if not shutil.which(name):
                continue
            try:
                subprocess.Popen(
                    command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except OSError as exc:
                print("archclip: auto-paste falhou:", exc)
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_REMOVE

    # ---------------------------------------------------------------- atalho

    def apply_hotkey(self) -> str:
        """(Re)registra o atalho global. Retorna "" ou a mensagem de erro."""
        if self.hotkey_backend is None:
            return "Nenhum backend de atalho disponível."

        # Devolve ao sistema o que tomamos da vez anterior. Sem isso, trocar
        # de Super+V para outra combinação deixaria a lista de notificações
        # sem atalho para sempre. Aplicar de novo logo em seguida é barato e
        # deixa a operação idempotente.
        if isinstance(self.hotkey_backend, GnomeHotkeyBackend):
            self.hotkey_backend.restore_conflicts()

        if not self.config.get("hotkey_enabled"):
            self.hotkey_backend.remove()
            return ""

        return self.hotkey_backend.apply(self.config.get("hotkey"))

    def _on_config_changed(self, key: str, value) -> None:
        if key == "max_items" and self.store is not None:
            self.store.trim(int(value))
            if self.window is not None and self.window.get_visible():
                self.window.refresh()

    # ---------------------------------------------------------- atualizações

    def _maybe_check_updates(self) -> bool:
        if updater.should_check(self.config):
            self._check_updates(manual=False)
        return GLib.SOURCE_REMOVE

    def _check_updates(self, manual: bool) -> None:
        def work() -> None:
            release, error = updater.check()
            GLib.idle_add(self._on_update_checked, release, error, manual)

        threading.Thread(target=work, daemon=True).start()

    def _on_update_checked(self, release, error: str, manual: bool) -> bool:
        self.config.set("update_last_check", time.time())
        if release is None:
            if manual and error:
                self._notify_error(error)
            return GLib.SOURCE_REMOVE

        if self.config.get("update_auto_install") and updater.can_self_install():
            self._install_update(release)
        else:
            notification = Gio.Notification.new("Nova versão do ArchClip")
            notification.set_body(
                "Versão {} disponível. Abra as configurações para atualizar.".format(
                    release.label
                )
            )
            self.send_notification("archclip-update", notification)
        return GLib.SOURCE_REMOVE

    def _install_update(self, release) -> None:
        def work() -> None:
            ok, message = updater.install(release)
            GLib.idle_add(self._on_update_installed, ok, message)

        threading.Thread(target=work, daemon=True).start()

    def _on_update_installed(self, ok: bool, message: str) -> bool:
        notification = Gio.Notification.new(
            "ArchClip atualizado" if ok else "Falha ao atualizar o ArchClip"
        )
        notification.set_body(message)
        self.send_notification("archclip-update", notification)
        return GLib.SOURCE_REMOVE

    def offer_update(self, release, parent=None) -> None:
        """Pergunta ao usuário se quer instalar a versão encontrada."""
        body = "Versão {} disponível (você tem a {}).".format(release.label, __version__)
        if release.notes:
            body += "\n\n" + release.notes[:400]

        dialog = Adw.MessageDialog(
            transient_for=parent or self.window,
            heading="Atualizar o ArchClip?",
            body=body,
        )
        dialog.add_response("later", "Depois")
        dialog.add_response("page", "Ver no GitHub")
        if updater.can_self_install():
            dialog.add_response("install", "Instalar")
            dialog.set_response_appearance("install", Adw.ResponseAppearance.SUGGESTED)
            dialog.set_default_response("install")
        dialog.set_close_response("later")
        dialog.connect("response", self._on_offer_response, release)
        dialog.present()

    def _on_offer_response(self, _dialog, response: str, release) -> None:
        if response == "install":
            self._install_update(release)
        elif response == "page":
            Gio.AppInfo.launch_default_for_uri(release.html_url, None)

    # ------------------------------------------------------------ utilidades

    def _notify_error(self, message: str) -> None:
        print("archclip:", message)
        if self.window is not None and self.window.get_visible():
            self.window.show_banner(message)

    def hotkey_label(self) -> str:
        return accel_label(self.config.get("hotkey"))


def _image_dimensions(data: bytes) -> tuple[int, int]:
    """Largura e altura da imagem, ou (0, 0) se o formato não for legível."""
    loader = GdkPixbuf.PixbufLoader()
    try:
        loader.write(data)
        loader.close()
    except GLib.Error:
        return 0, 0
    pixbuf = loader.get_pixbuf()
    if pixbuf is None:
        return 0, 0
    return pixbuf.get_width(), pixbuf.get_height()
