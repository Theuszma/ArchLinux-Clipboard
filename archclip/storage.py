"""Histórico persistido em SQLite. Texto inline, imagens como blobs em disco."""

from __future__ import annotations

import sqlite3
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .util import BLOB_DIR, DB_PATH, FILE_MODE, THUMB_DIR, ensure_dirs, harden, sha256_bytes

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT    NOT NULL,
    mime       TEXT    NOT NULL,
    hash       TEXT    NOT NULL UNIQUE,
    text       TEXT,
    blob_path  TEXT,
    preview    TEXT    NOT NULL DEFAULT '',
    width      INTEGER NOT NULL DEFAULT 0,
    height     INTEGER NOT NULL DEFAULT 0,
    size       INTEGER NOT NULL DEFAULT 0,
    pinned     INTEGER NOT NULL DEFAULT 0,
    created_at REAL    NOT NULL,
    updated_at REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_order ON items (pinned DESC, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_kind  ON items (kind);
"""


def normalize_search(value: Optional[str]) -> str:
    """Minúsculas e sem acentos, para comparar termos de busca.

    O conteúdo é sempre guardado em UTF-8 intacto -- isto vale só para o
    casamento da busca. O `COLLATE NOCASE` do SQLite dobra apenas A-Z, então
    sem esta normalização "AÇÃO" não acharia "ação" (Ç e ç são caracteres
    distintos para ele), nem "acao" acharia "ação".
    """
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFD", str(value))
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    return without_marks.casefold()


def like_pattern(query: str) -> str:
    """Termo de busca como padrão LIKE, com % e _ tratados como literais.

    Sem isso, procurar por "100%" ou "a_b" viraria curinga e traria a lista
    inteira.
    """
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + escaped + "%"


@dataclass
class Item:
    id: int
    kind: str  # "text" | "image"
    mime: str
    hash: str
    text: Optional[str]
    blob_path: Optional[str]
    preview: str
    width: int
    height: int
    size: int
    pinned: bool
    created_at: float
    updated_at: float

    @property
    def is_image(self) -> bool:
        return self.kind == "image"

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Item":
        return cls(
            id=row["id"],
            kind=row["kind"],
            mime=row["mime"],
            hash=row["hash"],
            text=row["text"],
            blob_path=row["blob_path"],
            preview=row["preview"],
            width=row["width"],
            height=row["height"],
            size=row["size"],
            pinned=bool(row["pinned"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class Store:
    """Acesso ao histórico. Usar sempre a partir da thread principal do GTK."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        ensure_dirs()
        self.db = sqlite3.connect(db_path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self.db.commit()
        self._harden_db_files(db_path)
        self._register_functions()

    def _register_functions(self) -> None:
        """Expõe normalize_search ao SQL, para a busca ignorar acento e caixa."""
        try:
            self.db.create_function(
                "archclip_norm", 1, normalize_search, deterministic=True
            )
        except sqlite3.NotSupportedError:  # SQLite anterior ao 3.8.3
            self.db.create_function("archclip_norm", 1, normalize_search)

    @staticmethod
    def _harden_db_files(db_path: Path) -> None:
        """O WAL e o -shm nascem com o umask do processo; fechamos os três."""
        for suffix in ("", "-wal", "-shm"):
            candidate = db_path.with_name(db_path.name + suffix)
            if candidate.exists():
                harden(candidate, FILE_MODE)

    def close(self) -> None:
        self.db.close()

    # ---------------------------------------------------------------- escrita

    def _touch_existing(self, digest: str) -> Optional[Item]:
        """Conteúdo repetido não duplica: só volta para o topo da lista."""
        row = self.db.execute("SELECT * FROM items WHERE hash = ?", (digest,)).fetchone()
        if row is None:
            return None
        now = time.time()
        self.db.execute("UPDATE items SET updated_at = ? WHERE id = ?", (now, row["id"]))
        self.db.commit()
        item = Item.from_row(row)
        item.updated_at = now
        return item

    def add_text(self, text: str, mime: str = "text/plain;charset=utf-8") -> Optional[Item]:
        if not text.strip():
            return None
        digest = sha256_bytes(text.encode("utf-8"))
        existing = self._touch_existing(digest)
        if existing:
            return existing

        now = time.time()
        preview = " ".join(text.split())[:400]
        cursor = self.db.execute(
            "INSERT INTO items (kind, mime, hash, text, preview, size, created_at, updated_at)"
            " VALUES ('text', ?, ?, ?, ?, ?, ?, ?)",
            (mime, digest, text, preview, len(text.encode("utf-8")), now, now),
        )
        self.db.commit()
        return self.get(cursor.lastrowid)

    def add_image(self, data: bytes, mime: str, width: int = 0, height: int = 0) -> Optional[Item]:
        if not data:
            return None
        digest = sha256_bytes(data)
        existing = self._touch_existing(digest)
        if existing:
            return existing

        suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(mime, ".bin")
        blob_path = BLOB_DIR / (digest + suffix)
        try:
            blob_path.write_bytes(data)
            harden(blob_path, FILE_MODE)
        except OSError as exc:
            print("archclip: falha ao gravar imagem:", exc)
            return None

        now = time.time()
        preview = "Imagem {}x{}".format(width, height) if width and height else "Imagem"
        cursor = self.db.execute(
            "INSERT INTO items (kind, mime, hash, blob_path, preview, width, height, size,"
            " created_at, updated_at) VALUES ('image', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (mime, digest, str(blob_path), preview, width, height, len(data), now, now),
        )
        self.db.commit()
        return self.get(cursor.lastrowid)

    # ---------------------------------------------------------------- leitura

    def get(self, item_id: int) -> Optional[Item]:
        row = self.db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return Item.from_row(row) if row else None

    def list(
        self,
        query: str = "",
        kind: Optional[str] = None,
        pinned_only: bool = False,
        limit: int = 500,
    ) -> list[Item]:
        """Fixados primeiro, depois do mais recente ao mais antigo."""
        sql = "SELECT * FROM items WHERE 1=1"
        params: list = []
        if query.strip():
            # `preview` é truncado em 400 caracteres, então buscar só nele
            # perderia o miolo de textos longos: procuramos também no conteúdo.
            sql += (
                " AND (archclip_norm(preview) LIKE ? ESCAPE '\\'"
                " OR archclip_norm(text) LIKE ? ESCAPE '\\')"
            )
            pattern = like_pattern(normalize_search(query.strip()))
            params.extend([pattern, pattern])
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if pinned_only:
            sql += " AND pinned = 1"
        sql += " ORDER BY pinned DESC, updated_at DESC LIMIT ?"
        params.append(limit)
        return [Item.from_row(row) for row in self.db.execute(sql, params)]

    def count(self) -> tuple[int, int]:
        """Retorna (total, fixados)."""
        row = self.db.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(pinned), 0) AS pinned FROM items"
        ).fetchone()
        return row["total"], row["pinned"]

    # --------------------------------------------------------------- mutações

    def set_pinned(self, item_id: int, pinned: bool) -> None:
        self.db.execute("UPDATE items SET pinned = ? WHERE id = ?", (1 if pinned else 0, item_id))
        self.db.commit()

    def toggle_pin(self, item_id: int) -> bool:
        item = self.get(item_id)
        if item is None:
            return False
        self.set_pinned(item_id, not item.pinned)
        return not item.pinned

    def delete(self, item_id: int) -> None:
        item = self.get(item_id)
        if item is None:
            return
        self.db.execute("DELETE FROM items WHERE id = ?", (item_id,))
        self.db.commit()
        self._drop_files(item)

    def clear(self, keep_pinned: bool = True) -> int:
        where = " WHERE pinned = 0" if keep_pinned else ""
        doomed = [Item.from_row(row) for row in self.db.execute("SELECT * FROM items" + where)]
        self.db.execute("DELETE FROM items" + where)
        self.db.commit()
        for item in doomed:
            self._drop_files(item)
        return len(doomed)

    def trim(self, max_items: int) -> int:
        """Descarta os não-fixados mais antigos que excedem o limite."""
        if max_items <= 0:
            return 0
        rows = self.db.execute(
            "SELECT * FROM items WHERE pinned = 0 ORDER BY updated_at DESC LIMIT -1 OFFSET ?",
            (max_items,),
        ).fetchall()
        if not rows:
            return 0
        doomed = [Item.from_row(row) for row in rows]
        self.db.executemany("DELETE FROM items WHERE id = ?", [(item.id,) for item in doomed])
        self.db.commit()
        for item in doomed:
            self._drop_files(item)
        return len(doomed)

    def _drop_files(self, item: Item) -> None:
        """Remove blob e thumbnail do item já apagado do banco."""
        paths = [THUMB_DIR / (item.hash + ".png")]
        if item.blob_path:
            paths.append(Path(item.blob_path))
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
