#!/usr/bin/env bash
# Remove o ArchClip e devolve ao GNOME os atalhos que ele tomou.
set -euo pipefail

APP_ID="io.github.theuszma.ArchClip"
EXT_UUID="archclip@theuszma.github.io"

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"

APP_ROOT="$DATA_HOME/archclip"
CONFIG_DIR="$CONFIG_HOME/archclip"
BIN_DIR="$HOME/.local/bin"

info()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }

KEEP_DATA=0
[[ "${1:-}" == "--keep-data" ]] && KEEP_DATA=1

# ------------------------------------------------------------------- daemon

info "Encerrando o daemon"
"$BIN_DIR/archclip" --quit >/dev/null 2>&1 || true

# ------------------------------------------------------------------- atalhos

info "Restaurando os atalhos do GNOME"
CONFIG_PATH="$CONFIG_DIR/config.json" python3 <<'PY' || true
import ast
import json
import os
import subprocess

MEDIA = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/archclip/"


def gsettings(*args):
    return subprocess.run(
        ["gsettings", *args], capture_output=True, text=True, timeout=10
    )


def as_variant(values):
    """Lista Python -> literal GVariant aceito pelo gsettings."""
    if not values:
        return "@as []"
    escaped = [v.replace("\\", "\\\\").replace("'", "\\'") for v in values]
    return "[" + ", ".join("'{}'".format(v) for v in escaped) + "]"


# 1. Devolve os aceleradores que tomamos dos atalhos nativos.
try:
    with open(os.environ["CONFIG_PATH"], encoding="utf-8") as handle:
        config = json.load(handle)
except (OSError, ValueError):
    config = {}

for marker, values in (config.get("overridden_bindings") or {}).items():
    schema, _, key = marker.rpartition(":")
    if not schema or not key:
        continue
    result = gsettings("set", schema, key, as_variant(list(values)))
    status = "ok" if result.returncode == 0 else result.stderr.strip()
    print("    {} {} -> {} [{}]".format(schema, key, as_variant(list(values)), status))

# 2. Tira nosso keybinding personalizado da lista do gnome-settings-daemon.
current = gsettings("get", MEDIA, "custom-keybindings").stdout.strip()
try:
    paths = ast.literal_eval(current) if current.startswith("[") else []
except (ValueError, SyntaxError):
    paths = []

remaining = [p for p in paths if p != CUSTOM_PATH]
if remaining != paths:
    gsettings("set", MEDIA, "custom-keybindings", as_variant(remaining))
    print("    keybinding do ArchClip removido")
PY

# ------------------------------------------------- extensão do GNOME Shell

info "Removendo a extensão do GNOME Shell"
# Desligar antes de apagar: assim o `disable()` da extensão tira o serviço do
# barramento e desconecta o sinal enquanto o código ainda existe.
gnome-extensions disable "$EXT_UUID" >/dev/null 2>&1 || true
rm -rf "${DATA_HOME:?}/gnome-shell/extensions/$EXT_UUID"

# ------------------------------------------------------------------ arquivos

info "Removendo arquivos instalados"
rm -f "$BIN_DIR/archclip"
rm -f "$DATA_HOME/applications/$APP_ID.desktop"
rm -f "$DATA_HOME/icons/hicolor/scalable/apps/$APP_ID.svg"
rm -f "$CONFIG_HOME/autostart/$APP_ID-daemon.desktop"
rm -rf "$APP_ROOT/versions" "$APP_ROOT/current"
rm -rf "$CACHE_HOME/archclip"

update-desktop-database "$DATA_HOME/applications" >/dev/null 2>&1 || true

if [[ $KEEP_DATA -eq 0 ]]; then
  info "Removendo histórico e configuração"
  rm -rf "$APP_ROOT" "$CONFIG_DIR"
else
  info "Histórico e configuração preservados em:"
  echo "    $APP_ROOT"
  echo "    $CONFIG_DIR"
fi

echo
green "ArchClip removido."
echo "Faça logout/login para o GNOME recarregar os atalhos e descarregar a"
echo "extensão do Shell."
