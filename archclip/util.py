"""Caminhos XDG, hashing e formatação compartilhados."""

from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime
from pathlib import Path


def _xdg(env: str, fallback: str) -> Path:
    value = os.environ.get(env)
    return Path(value) if value else Path.home() / fallback


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "archclip"
DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / "archclip"
CACHE_DIR = _xdg("XDG_CACHE_HOME", ".cache") / "archclip"

CONFIG_PATH = CONFIG_DIR / "config.json"
DB_PATH = DATA_DIR / "history.db"
BLOB_DIR = DATA_DIR / "blobs"
THUMB_DIR = CACHE_DIR / "thumbs"

AUTOSTART_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "autostart"

# O histórico guarda em texto puro tudo o que passou pela área de
# transferência -- senhas e tokens inclusive. Num sistema com mais de um
# usuário, o padrão do umask (755/644) deixaria isso legível por todos, então
# restringimos ao dono.
DIR_MODE = 0o700
FILE_MODE = 0o600


def harden(path: Path, mode: int) -> None:
    """Restringe as permissões ao dono, ignorando sistemas que não suportam."""
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def ensure_dirs() -> None:
    for path in (CONFIG_DIR, DATA_DIR, CACHE_DIR, BLOB_DIR, THUMB_DIR):
        # O mode do mkdir passa pelo umask, então reforçamos com chmod.
        path.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
        harden(path, DIR_MODE)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def elide(text: str, limit: int = 220) -> str:
    """Colapsa espaços em branco e corta em `limit` caracteres."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def human_time(timestamp: float) -> str:
    """Timestamp relativo em pt-BR: 'agora', 'há 5 min', 'ontem 14:03'."""
    delta = time.time() - timestamp
    if delta < 45:
        return "agora"
    if delta < 3600:
        return f"há {int(delta // 60)} min"
    if delta < 86400:
        hours = int(delta // 3600)
        return f"há {hours} h" if hours > 1 else "há 1 h"

    moment = datetime.fromtimestamp(timestamp)
    today = datetime.now().date()
    days = (today - moment.date()).days
    if days == 1:
        return f"ontem {moment:%H:%M}"
    if days < 7:
        return f"{days} dias atrás"
    return f"{moment:%d/%m/%Y}"


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
