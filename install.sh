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
echo "  • O daemon já está rodando e registrou o atalho Super+V."
echo "    (o atalho nativo do GNOME para a lista de notificações foi liberado;"
echo "     Super+M continua abrindo as notificações)"
echo "  • Abra as configurações com:  archclip --settings"
echo "  • Para desinstalar:           ./uninstall.sh"
echo
echo "Se o Super+V não responder de imediato, faça logout/login para o"
echo "gnome-settings-daemon recarregar os atalhos."
