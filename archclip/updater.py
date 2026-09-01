"""Verificação e instalação de atualizações via GitHub Releases.

Só instala sozinho quando o app foi instalado no diretório do usuário pelo
install.sh (layout ~/.local/share/archclip/versions/<versão> com o symlink
`current`). Se veio do pacman/AUR ou está rodando do checkout de código, o
updater apenas avisa -- mexer numa árvore gerenciada por outra ferramenta só
causaria confusão.
"""

from __future__ import annotations

import json
import os
import shutil
import ssl
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import GITHUB_REPO, __version__
from .config import Config
from .util import DATA_DIR

API_URL = "https://api.github.com/repos/{}/releases/latest".format(GITHUB_REPO)
RELEASES_URL = "https://github.com/{}/releases".format(GITHUB_REPO)
USER_AGENT = "ArchClip/{} (+https://github.com/{})".format(__version__, GITHUB_REPO)

VERSIONS_DIR = DATA_DIR / "versions"
CURRENT_LINK = DATA_DIR / "current"

CHECK_INTERVAL = 24 * 3600
NETWORK_TIMEOUT = 15
MAX_DOWNLOAD = 64 * 1024 * 1024

# O tarball vem de uma URL que lemos de um JSON: mesmo com TLS, vale recusar
# qualquer destino fora do GitHub antes de baixar e executar aquele código.
# `tarball_url` sai de api.github.com e redireciona para codeload.
TRUSTED_HOSTS = frozenset(
    {
        "api.github.com",
        "github.com",
        "codeload.github.com",
        "objects.githubusercontent.com",
    }
)


@dataclass
class Release:
    version: tuple[int, ...]
    tag: str
    notes: str
    tarball_url: str
    html_url: str

    @property
    def label(self) -> str:
        return ".".join(str(part) for part in self.version)


def parse_version(raw: str) -> tuple[int, ...]:
    """'v1.2.3' -> (1, 2, 3). Partes não numéricas viram 0."""
    cleaned = (raw or "").strip().lstrip("vV").split("-")[0].split("+")[0]
    parts: list[int] = []
    for chunk in cleaned.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


CURRENT_VERSION = parse_version(__version__)


# ------------------------------------------------------------------ instalação


def install_kind() -> str:
    """Como este app foi instalado: 'local', 'package' ou 'source'."""
    here = Path(__file__).resolve()
    try:
        here.relative_to(VERSIONS_DIR.resolve())
        return "local"
    except (ValueError, OSError):
        pass
    if str(here).startswith(("/usr/", "/opt/")):
        return "package"
    return "source"


def can_self_install() -> bool:
    return install_kind() == "local"


def why_not_self_install() -> str:
    kind = install_kind()
    if kind == "package":
        return "Instalado por pacote do sistema: atualize com o pacman/AUR."
    if kind == "source":
        return "Rodando do código-fonte: atualize com git pull."
    return ""


# ---------------------------------------------------------------- verificação


def should_check(config: Config) -> bool:
    if not config.get("update_check"):
        return False
    last = float(config.get("update_last_check") or 0)
    return time.time() - last >= CHECK_INTERVAL


def check(timeout: int = NETWORK_TIMEOUT) -> tuple[Optional[Release], str]:
    """Consulta a release mais recente. Bloqueia -- chamar fora da thread do GTK.

    Retorna (release_mais_nova_ou_None, mensagem_de_erro).
    """
    request = urllib.request.Request(
        API_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            payload = json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, "Nenhuma release publicada ainda."
        return None, "GitHub respondeu {}".format(exc.code)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, "Sem conexão com o GitHub: {}".format(exc)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, "Resposta inesperada do GitHub: {}".format(exc)

    tag = payload.get("tag_name") or ""
    if not tag:
        return None, "Release sem tag."
    version = parse_version(tag)
    if version <= CURRENT_VERSION:
        return None, ""

    return (
        Release(
            version=version,
            tag=tag,
            notes=(payload.get("body") or "").strip(),
            tarball_url=payload.get("tarball_url") or "",
            html_url=payload.get("html_url") or RELEASES_URL,
        ),
        "",
    )


# ----------------------------------------------------------------- instalação


def is_trusted_url(url: str) -> bool:
    """True se a URL for HTTPS e apontar para um host do GitHub."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return parts.scheme == "https" and (parts.hostname or "").lower() in TRUSTED_HOSTS


def _download(url: str, destination: Path, timeout: int) -> str:
    if not is_trusted_url(url):
        return "URL de download recusada (fora do GitHub): {}".format(url)

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            # urlopen segue redirecionamentos sozinho; conferimos onde parou.
            if not is_trusted_url(response.geturl()):
                return "Redirecionamento para fora do GitHub: {}".format(response.geturl())
            written = 0
            with open(destination, "wb") as handle:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_DOWNLOAD:
                        return "Download excedeu {} MB.".format(MAX_DOWNLOAD // (1024 * 1024))
                    handle.write(chunk)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return "Falha no download: {}".format(exc)
    return ""


def _extract(archive: Path, target: Path) -> str:
    try:
        with tarfile.open(archive, "r:gz") as tar:
            # `filter='data'` recusa caminhos absolutos, '..' e links fora da
            # árvore -- indispensável ao extrair algo baixado da rede.
            try:
                tar.extractall(target, filter="data")
            except TypeError:
                # Python antigo demais para extração segura. Extrair assim
                # mesmo permitiria a um tarball malicioso escrever fora de
                # `target`, então preferimos falhar e mandar atualizar na mão.
                return (
                    "Este Python não suporta extração segura de tarballs "
                    "(tarfile filter='data'). Atualize o Python ou instale a "
                    "nova versão manualmente."
                )
    except (tarfile.TarError, OSError) as exc:
        return "Falha ao extrair: {}".format(exc)
    return ""


def _find_package_root(tree: Path) -> Optional[Path]:
    """Diretório que contém o pacote `archclip/` dentro do tarball extraído."""
    if (tree / "archclip" / "__init__.py").is_file():
        return tree
    for child in sorted(tree.iterdir()):
        if child.is_dir() and (child / "archclip" / "__init__.py").is_file():
            return child
    return None


def install(release: Release, timeout: int = NETWORK_TIMEOUT) -> tuple[bool, str]:
    """Baixa e instala a release. Bloqueia -- chamar fora da thread do GTK."""
    if not can_self_install():
        return False, why_not_self_install()
    if not release.tarball_url:
        return False, "Release sem tarball para baixar."

    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    destination = VERSIONS_DIR / release.label

    with tempfile.TemporaryDirectory(prefix="archclip-update-") as workdir:
        work = Path(workdir)
        archive = work / "release.tar.gz"

        error = _download(release.tarball_url, archive, timeout)
        if error:
            return False, error

        extracted = work / "tree"
        extracted.mkdir()
        error = _extract(archive, extracted)
        if error:
            return False, error

        source = _find_package_root(extracted)
        if source is None:
            return False, "O tarball não contém o pacote archclip/."

        staging = VERSIONS_DIR / (release.label + ".incoming")
        shutil.rmtree(staging, ignore_errors=True)
        try:
            shutil.move(str(source), str(staging))
        except OSError as exc:
            return False, "Falha ao mover os arquivos: {}".format(exc)

    # Troca a versão instalada só depois que tudo já está em disco.
    try:
        if destination.exists():
            shutil.rmtree(destination)
        staging.rename(destination)
        _point_current_to(destination)
    except OSError as exc:
        return False, "Falha ao ativar a nova versão: {}".format(exc)

    _prune_old_versions(keep=release.label)
    return True, "Versão {} instalada. Reinicie o ArchClip para aplicar.".format(release.label)


def _point_current_to(destination: Path) -> None:
    """Aponta o symlink `current` para a versão nova, de forma atômica."""
    temporary = CURRENT_LINK.with_name("current.new")
    if temporary.is_symlink() or temporary.exists():
        temporary.unlink()
    temporary.symlink_to(destination, target_is_directory=True)
    os.replace(temporary, CURRENT_LINK)


def _prune_old_versions(keep: str, retain: int = 2) -> None:
    """Mantém apenas as versões mais recentes, mais a que está ativa."""
    try:
        versions = sorted(
            (path for path in VERSIONS_DIR.iterdir() if path.is_dir()),
            key=lambda path: parse_version(path.name),
            reverse=True,
        )
    except OSError:
        return
    for path in versions[retain:]:
        if path.name == keep:
            continue
        shutil.rmtree(path, ignore_errors=True)

