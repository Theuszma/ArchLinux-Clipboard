"""Início automático via arquivo .desktop em ~/.config/autostart."""

from __future__ import annotations

from . import APP_ID, APP_NAME
from .hotkey import launcher_command
from .util import AUTOSTART_DIR

AUTOSTART_FILE = AUTOSTART_DIR / (APP_ID + "-daemon.desktop")

TEMPLATE = """[Desktop Entry]
Type=Application
Name={name}
Comment=Histórico da área de transferência em segundo plano
Exec={exec}
Icon={icon}
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=3
"""


def is_enabled() -> bool:
    return AUTOSTART_FILE.is_file()


def set_enabled(enabled: bool) -> str:
    """Liga/desliga o autostart. Retorna "" em sucesso ou a mensagem de erro."""
    try:
        if enabled:
            AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
            AUTOSTART_FILE.write_text(
                TEMPLATE.format(
                    name=APP_NAME + " (daemon)",
                    exec=launcher_command("--daemon"),
                    icon=APP_ID,
                ),
                encoding="utf-8",
            )
        else:
            AUTOSTART_FILE.unlink(missing_ok=True)
    except OSError as exc:
        return str(exc)
    return ""


def refresh() -> None:
    """Reescreve o arquivo se ele existir, para atualizar o caminho do Exec."""
    if is_enabled():
        set_enabled(True)
