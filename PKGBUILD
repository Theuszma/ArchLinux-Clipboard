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
  install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
}
