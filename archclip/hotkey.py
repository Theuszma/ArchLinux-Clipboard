"""Registro do atalho global.

No Wayland um aplicativo comum não pode capturar teclas globalmente -- quem
faz isso é o compositor. No GNOME, então, gravamos um "custom keybinding" via
GSettings e, antes disso, tiramos o mesmo acelerador de qualquer atalho nativo
que já o use (é o caso do Super+V, ligado por padrão à lista de notificações
em org.gnome.shell.keybindings/toggle-message-tray).

Os valores originais ficam salvos na config para poderem ser restaurados.
"""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Optional

from .gtkdeps import Gdk, GLib, Gio, Gtk

from .config import Config
from .util import DATA_DIR

MEDIA_KEYS_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
CUSTOM_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/archclip/"

# Schemas do GNOME que podem conter o acelerador que queremos usar.
CONFLICT_SCHEMAS = (
    "org.gnome.shell.keybindings",
    "org.gnome.desktop.wm.keybindings",
    "org.gnome.settings-daemon.plugins.media-keys",
    "org.gnome.mutter.keybindings",
    "org.gnome.mutter.wayland.keybindings",
)


# --------------------------------------------------------------- aceleradores


def normalize_accel(accel: str) -> str:
    """Forma canônica de um acelerador, ou "" se for inválido.

    '<Super>V' e '<super>v' viram ambos '<Super>v', para comparar com o que o
    GNOME tem gravado.
    """
    ok, keyval, mods = Gtk.accelerator_parse(accel or "")
    if not ok or keyval == 0:
        return ""
    if not mods & Gdk.ModifierType.SHIFT_MASK:
        keyval = Gdk.keyval_to_lower(keyval)
    return Gtk.accelerator_name(keyval, mods)


def accel_label(accel: str) -> str:
    """Rótulo legível: '<Super>v' -> 'Super+V'."""
    ok, keyval, mods = Gtk.accelerator_parse(accel or "")
    if not ok or keyval == 0:
        return "Nenhum"
    return Gtk.accelerator_get_label(keyval, mods)


def is_valid_accel(accel: str) -> bool:
    ok, keyval, mods = Gtk.accelerator_parse(accel or "")
    if not ok or keyval == 0:
        return False
    # Exige ao menos um modificador, senão o atalho engoliria uma tecla comum.
    useful = (
        Gdk.ModifierType.CONTROL_MASK
        | Gdk.ModifierType.ALT_MASK
        | Gdk.ModifierType.SUPER_MASK
        | Gdk.ModifierType.META_MASK
    )
    return bool(mods & useful)


# ------------------------------------------------------------------- comandos


def launcher_command(argument: str) -> str:
    """Linha de comando que o compositor vai executar ao apertar o atalho."""
    installed = shutil.which("archclip")
    if installed:
        return "{} {}".format(shlex.quote(installed), argument)

    # Sem launcher no PATH, montamos a chamada na mão. Preferimos o symlink
    # `current` ao diretório versionado: assim o atalho continua valendo
    # depois de uma atualização.
    root = Path(__file__).resolve().parent.parent
    current = DATA_DIR / "current"
    if (current / "archclip" / "__init__.py").is_file():
        root = current
    return "env PYTHONPATH={} {} -m archclip {}".format(
        shlex.quote(str(root)), shlex.quote(sys.executable), argument
    )


def desktop_environment() -> str:
    raw = os.environ.get("XDG_CURRENT_DESKTOP", "") or os.environ.get("DESKTOP_SESSION", "")
    return raw.lower()


# ------------------------------------------------------------------- backends


def _schema(schema_id: str) -> Optional[Gio.SettingsSchema]:
    source = Gio.SettingsSchemaSource.get_default()
    if source is None:
        return None
    return source.lookup(schema_id, True)


class HotkeyBackend:
    """Interface comum aos gerenciadores de atalho."""

    name = "manual"
    automatic = False

    def apply(self, accel: str) -> str:
        """Registra o atalho. Retorna "" em sucesso ou a mensagem de erro."""
        return "Registro automático não suportado neste ambiente."

    def remove(self) -> None:
        pass

    def instructions(self, accel: str) -> str:
        return (
            "Registre manualmente o atalho {} para o comando:\n{}".format(
                accel_label(accel), launcher_command("--toggle")
            )
        )


class GnomeHotkeyBackend(HotkeyBackend):
    name = "gnome"
    automatic = True

    def __init__(self, config: Config) -> None:
        self.config = config

    @staticmethod
    def available() -> bool:
        return _schema(MEDIA_KEYS_SCHEMA) is not None and _schema(CUSTOM_SCHEMA) is not None

    # -------------------------------------------------------------- conflitos

    def _find_conflicts(self, accel: str) -> list[tuple[str, str, list[str]]]:
        """Atalhos nativos que usam `accel`: [(schema, key, valores)]."""
        target = normalize_accel(accel)
        found: list[tuple[str, str, list[str]]] = []
        if not target:
            return found

        for schema_id in CONFLICT_SCHEMAS:
            schema = _schema(schema_id)
            if schema is None:
                continue
            settings = Gio.Settings.new(schema_id)
            for key in schema.list_keys():
                if schema.get_key(key).get_value_type().dup_string() != "as":
                    continue
                values = list(settings.get_strv(key))
                if any(normalize_accel(value) == target for value in values):
                    found.append((schema_id, key, values))
        return found

    def _release_conflicts(self, accel: str) -> list[str]:
        """Remove `accel` dos atalhos nativos, guardando o valor original."""
        target = normalize_accel(accel)
        overridden = dict(self.config.get("overridden_bindings") or {})
        touched: list[str] = []

        for schema_id, key, values in self._find_conflicts(accel):
            settings = Gio.Settings.new(schema_id)
            remaining = [v for v in values if normalize_accel(v) != target]
            marker = "{}:{}".format(schema_id, key)
            # Só guarda o original na primeira vez, para não sobrescrever o
            # backup com um valor que nós mesmos já reduzimos.
            overridden.setdefault(marker, values)
            settings.set_strv(key, remaining)
            touched.append(marker)

        if touched:
            Gio.Settings.sync()
            self.config.set("overridden_bindings", overridden)
        return touched

    def restore_conflicts(self) -> None:
        """Devolve aos atalhos nativos os aceleradores que tomamos."""
        overridden = self.config.get("overridden_bindings") or {}
        for marker, values in overridden.items():
            schema_id, _, key = marker.rpartition(":")
            if not schema_id or _schema(schema_id) is None:
                continue
            try:
                Gio.Settings.new(schema_id).set_strv(key, list(values))
            except GLib.Error as exc:
                print("archclip: falha ao restaurar", marker, exc)
        Gio.Settings.sync()
        self.config.set("overridden_bindings", {})

    # ---------------------------------------------------------------- registro

    def apply(self, accel: str) -> str:
        normalized = normalize_accel(accel)
        if not normalized:
            return "Acelerador inválido: {}".format(accel)
        if not self.available():
            return "Schemas do GNOME não encontrados (gnome-settings-daemon está instalado?)."

        # 1. Libera o acelerador de quem já o usa (ex.: lista de notificações).
        self._release_conflicts(normalized)

        # 2. Grava nosso keybinding personalizado.
        custom = Gio.Settings.new_with_path(CUSTOM_SCHEMA, CUSTOM_PATH)
        custom.set_string("name", "Área de Transferência (ArchClip)")
        custom.set_string("command", launcher_command("--toggle"))
        custom.set_string("binding", normalized)

        # 3. Garante que o caminho está na lista que o daemon lê.
        media = Gio.Settings.new(MEDIA_KEYS_SCHEMA)
        paths = list(media.get_strv("custom-keybindings"))
        if CUSTOM_PATH not in paths:
            paths.append(CUSTOM_PATH)
            media.set_strv("custom-keybindings", paths)

        Gio.Settings.sync()
        return ""

    def remove(self) -> None:
        if not self.available():
            return
        media = Gio.Settings.new(MEDIA_KEYS_SCHEMA)
        paths = [p for p in media.get_strv("custom-keybindings") if p != CUSTOM_PATH]
        media.set_strv("custom-keybindings", paths)

        custom = Gio.Settings.new_with_path(CUSTOM_SCHEMA, CUSTOM_PATH)
        for key in ("name", "command", "binding"):
            custom.reset(key)
        Gio.Settings.sync()

    def conflicts_for(self, accel: str) -> list[str]:
        """Nomes legíveis dos atalhos nativos que seriam sobrescritos."""
        return ["{}/{}".format(schema, key) for schema, key, _ in self._find_conflicts(accel)]


def detect_backend(config: Config) -> HotkeyBackend:
    desktop = desktop_environment()
    if "gnome" in desktop and GnomeHotkeyBackend.available():
        return GnomeHotkeyBackend(config)
    if GnomeHotkeyBackend.available():
        # Sessão não identificada como GNOME, mas os schemas existem.
        return GnomeHotkeyBackend(config)
    return HotkeyBackend()
