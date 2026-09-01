# Maintainer: Theuszma <matheusvictorbarbosa@usp.br>
pkgname=archclip
pkgver=0.1.0
pkgrel=1
pkgdesc="Histórico da área de transferência para Arch Linux, no estilo do Win+V"
arch=('any')
url="https://github.com/Theuszma/ArchLinux-Clipboard"
license=('MIT')
depends=('python' 'python-gobject' 'gtk4' 'libadwaita' 'wl-clipboard')
optdepends=(
  'gnome-shell>=45: captura em segundo plano, pela extensão do Shell'
  'xclip: suporte a sessões X11'
  'ydotool: colar automaticamente após escolher um item'
)
makedepends=('python-build' 'python-installer' 'python-setuptools' 'python-wheel')
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('SKIP')

_srcdir="ArchLinux-Clipboard-$pkgver"

build() {
  cd "$_srcdir"
  python -m build --wheel --no-isolation
}

package() {
  cd "$_srcdir"
  python -m installer --destdir="$pkgdir" dist/*.whl

  install -Dm644 "data/io.github.theuszma.ArchClip.desktop" \
    "$pkgdir/usr/share/applications/io.github.theuszma.ArchClip.desktop"
  install -Dm644 "data/icons/io.github.theuszma.ArchClip.svg" \
    "$pkgdir/usr/share/icons/hicolor/scalable/apps/io.github.theuszma.ArchClip.svg"
  # A extensão do GNOME Shell é o que enxerga a área de transferência em
  # segundo plano: o Mutter não implementa data-control. Instalada, ainda
  # precisa ser ligada (gnome-extensions enable) e vale a partir do próximo
  # login -- o Shell carrega extensões uma vez por sessão.
  local _extdir="$pkgdir/usr/share/gnome-shell/extensions/archclip@theuszma.github.io"
  install -dm755 "$_extdir"
  install -m644 extension/* "$_extdir/"

  install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
}
