#!/usr/bin/env bash
# Instala o ArchClip no diretório do usuário (sem sudo).
#
# Layout resultante:
#   ~/.local/share/archclip/versions/<versão>/archclip/   código
#   ~/.local/share/archclip/current -> versions/<versão>  symlink que o
#                                                         updater troca
#   ~/.local/bin/archclip                                 launcher
set -euo pipefail

APP_ID="io.github.theuszma.ArchClip"
EXT_UUID="archclip@theuszma.github.io"
EXT_BUS_NAME="io.github.theuszma.ArchClip.Shell"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_ROOT="$DATA_HOME/archclip"
BIN_DIR="$HOME/.local/bin"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
info()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[33m==> %s\033[0m\n' "$*"; }

# ------------------------------------------------------------------ validação

if [[ ! -f "$SOURCE_DIR/archclip/__init__.py" ]]; then
  red "Erro: rode este script a partir da raiz do repositório."
  exit 1
fi

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SOURCE_DIR/archclip/__init__.py")"
if [[ -z "$VERSION" ]]; then
  red "Erro: não consegui ler a versão de archclip/__init__.py."
  exit 1
fi

info "Instalando ArchClip $VERSION"

# ---------------------------------------------------------------- dependências

missing_pkgs=()

if ! command -v python3 >/dev/null 2>&1; then
  missing_pkgs+=("python")
fi

if ! python3 -c 'import gi' >/dev/null 2>&1; then
  missing_pkgs+=("python-gobject")
fi

if ! python3 - <<'PY' >/dev/null 2>&1
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: F401
PY
then
  missing_pkgs+=("gtk4" "libadwaita")
fi

# O daemon depende do wl-clipboard no Wayland e do xclip no X11.
if [[ "${XDG_SESSION_TYPE:-}" == "wayland" || -n "${WAYLAND_DISPLAY:-}" ]]; then
  command -v wl-paste >/dev/null 2>&1 || missing_pkgs+=("wl-clipboard")
else
  command -v xclip >/dev/null 2>&1 || missing_pkgs+=("xclip")
fi

if [[ ${#missing_pkgs[@]} -gt 0 ]]; then
  # Remove duplicatas mantendo a ordem.
  mapfile -t missing_pkgs < <(printf '%s\n' "${missing_pkgs[@]}" | awk '!seen[$0]++')
  red "Faltam dependências. Instale com:"
  echo
  echo "    sudo pacman -S --needed ${missing_pkgs[*]}"
  echo
  exit 1
fi

green "Dependências OK."

# -------------------------------------------------------------------- cópia

VERSION_DIR="$APP_ROOT/versions/$VERSION"

info "Copiando para $VERSION_DIR"
mkdir -p "$VERSION_DIR"
rm -rf "${VERSION_DIR:?}/archclip"
cp -r "$SOURCE_DIR/archclip" "$VERSION_DIR/archclip"
# __pycache__ do host não serve para nada aqui e ainda confunde diffs.
find "$VERSION_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

# Symlink atômico: cria ao lado e move por cima.
ln -sfn "$VERSION_DIR" "$APP_ROOT/current.new"
mv -T "$APP_ROOT/current.new" "$APP_ROOT/current"

# ----------------------------------------------------------------- launcher

info "Instalando launcher em $BIN_DIR/archclip"
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/archclip" <<LAUNCHER
#!/bin/sh
# Gerado por install.sh do ArchClip. Aponta para o symlink 'current', então
# continua válido depois que o updater troca a versão instalada.
APP_DIR="$APP_ROOT/current"
exec env PYTHONPATH="\$APP_DIR\${PYTHONPATH:+:\$PYTHONPATH}" python3 -m archclip "\$@"
LAUNCHER
chmod +x "$BIN_DIR/archclip"

# ------------------------------------------------------------ desktop e ícone

info "Registrando o aplicativo no menu"
install -Dm644 "$SOURCE_DIR/data/$APP_ID.desktop" \
  "$DATA_HOME/applications/$APP_ID.desktop"
install -Dm644 "$SOURCE_DIR/data/icons/$APP_ID.svg" \
  "$DATA_HOME/icons/hicolor/scalable/apps/$APP_ID.svg"

update-desktop-database "$DATA_HOME/applications" >/dev/null 2>&1 || true
gtk-update-icon-cache -qtf "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true

# ------------------------------------------------- extensão do GNOME Shell

# É ela quem vigia a área de transferência. O Mutter não implementa
# data-control (nem o wlr nem o ext), então `wl-paste --watch` não funciona no
# GNOME e um processo comum só enxerga a seleção enquanto tem foco de teclado.
# Dentro do Shell essa limitação não existe.

EXT_DIR="$DATA_HOME/gnome-shell/extensions/$EXT_UUID"
EXT_READY=0
EXT_REINSTALL=0
EXT_APPLICABLE=0

# Põe o UUID na lista de extensões habilitadas do GNOME, preservando o que já
# estava lá. É o que faz o próximo login subir com ela ligada, mesmo quando o
# Shell atual ainda não conhece a extensão.
ext_mark_enabled() {
  EXT_UUID="$EXT_UUID" python3 <<'PY'
import ast
import os
import subprocess

uuid = os.environ["EXT_UUID"]
current = subprocess.run(
    ["gsettings", "get", "org.gnome.shell", "enabled-extensions"],
    capture_output=True, text=True, timeout=10,
).stdout.strip()
try:
    enabled = ast.literal_eval(current) if current.startswith("[") else []
except (ValueError, SyntaxError):
    enabled = []
if uuid in enabled:
    raise SystemExit(0)
enabled.append(uuid)
value = "[" + ", ".join("'{}'".format(v) for v in enabled) + "]"
subprocess.run(
    ["gsettings", "set", "org.gnome.shell", "enabled-extensions", value], timeout=10
)
# A lista inteira é reescrita, então vale mostrar como ela ficou: se algo
# tiver sumido daqui, é este o lugar onde dá para perceber.
print("    extensões habilitadas: {}".format(value))
PY
}

ext_service_up() {
  gdbus call --session \
    --dest org.freedesktop.DBus \
    --object-path /org/freedesktop/DBus \
    --method org.freedesktop.DBus.NameHasOwner "$EXT_BUS_NAME" 2>/dev/null |
    grep -q true
}

if [[ "${XDG_CURRENT_DESKTOP:-}" == *GNOME* ]]; then
  EXT_APPLICABLE=1
  info "Instalando a extensão do GNOME Shell"
  [[ -f "$EXT_DIR/metadata.json" ]] && EXT_REINSTALL=1
  mkdir -p "$EXT_DIR"
  install -m644 "$SOURCE_DIR"/extension/* "$EXT_DIR/"

  if [[ "$(gsettings get org.gnome.shell disable-user-extensions 2>/dev/null)" == "true" ]]; then
    warn "As extensões de usuário estão desligadas no GNOME. Ligue com:"
    warn "    gsettings set org.gnome.shell disable-user-extensions false"
  fi

  # O GNOME Shell varre o diretório de extensões uma vez, no início da sessão
  # (no Wayland ele não pode se reiniciar), então uma extensão recém-copiada
  # ainda não existe para ele. Marcar o UUID como habilitado é o que garante
  # que o próximo login já suba com ela.
  ext_mark_enabled

  # Se o Shell já conhece o UUID (reinstalação), dá para ligar agora mesmo.
  # Quem decide se valeu é o serviço no barramento: só ele prova que a
  # extensão foi carregada de verdade.
  if gnome-extensions list 2>/dev/null | grep -qx "$EXT_UUID"; then
    gnome-extensions enable "$EXT_UUID" >/dev/null 2>&1 || true
    for _ in 1 2 3 4 5 6; do
      ext_service_up && { EXT_READY=1; break; }
      sleep 0.5
    done
  fi

  if [[ $EXT_READY -eq 1 ]]; then
    green "Extensão ativa."
  else
    warn "A extensão está instalada e marcada para ligar, mas o GNOME Shell só"
    warn "carrega extensões novas no começo da sessão. Faça logout/login e o"
    warn "histórico passa a encher sozinho."
  fi

  if [[ $EXT_REINSTALL -eq 1 ]]; then
    warn "A extensão já estava instalada, e o GNOME Shell mantém em memória o"
    warn "código que carregou. Faça logout/login para rodar a versão nova."
  fi
else
  warn "Sessão não-GNOME: a extensão do Shell não se aplica."
  warn "A captura vai depender do data-control do seu compositor."
fi

# ------------------------------------------------------------------- daemon

if ! printf '%s' ":$PATH:" | grep -q ":$BIN_DIR:"; then
  warn "$BIN_DIR não está no seu PATH."
  warn "Adicione ao ~/.bashrc ou ~/.zshrc:  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

info "Reiniciando o daemon"
"$BIN_DIR/archclip" --quit >/dev/null 2>&1 || true
sleep 1
setsid "$BIN_DIR/archclip" --daemon >/dev/null 2>&1 < /dev/null &
disown 2>/dev/null || true

echo
green "ArchClip $VERSION instalado."
echo
if [[ $EXT_READY -eq 1 ]]; then
  echo "  • A extensão do GNOME Shell está ativa: é ela quem vigia o clipboard."
elif [[ $EXT_APPLICABLE -eq 1 ]]; then
  echo "  • Faça logout/login para o GNOME Shell carregar a extensão do"
  echo "    ArchClip -- é ela quem vigia a área de transferência."
fi
echo "  • O daemon já está rodando e registrou o atalho Super+V."
echo "    (o atalho nativo do GNOME para a lista de notificações foi liberado;"
echo "     Super+M continua abrindo as notificações)"
echo "  • Abra as configurações com:  archclip --settings"
echo "  • Para desinstalar:           ./uninstall.sh"
echo
echo "Se o Super+V não responder de imediato, faça logout/login para o"
echo "gnome-settings-daemon recarregar os atalhos."
