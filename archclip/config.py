"""Configuração persistida em JSON (~/.config/archclip/config.json)."""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Callable

from .util import CONFIG_PATH, FILE_MODE, ensure_dirs, harden

DEFAULTS: dict[str, Any] = {
    # Histórico
    "max_items": 25,
    "capture_text": True,
    "capture_images": True,
    "max_item_size_mb": 16,
    # Atalho global
    "hotkey": "<Super>v",
    "hotkey_enabled": True,
    # Atalhos do sistema que sobrescrevemos, para poder restaurar depois.
    # Formato: {"schema:key": ["<Super>v", "<Super>m"]}
    "overridden_bindings": {},
    # Janela
    "close_on_copy": True,
    "close_on_focus_loss": True,
    "auto_paste": False,
    # Sistema
    "autostart": True,
    "update_check": True,
    # Desligado por padrão de propósito: as releases não são assinadas, então
    # instalar sozinho transformaria um comprometimento da conta do GitHub em
    # execução de código na máquina do usuário. Ligável nas configurações.
    "update_auto_install": False,
    "update_last_check": 0.0,
    # Privacidade
    "ignore_password_managers": True,
    "clear_on_exit": False,
}


class Config:
    """Dicionário de configuração com escrita atômica e observadores."""

    def __init__(self, path=CONFIG_PATH) -> None:
        self.path = path
        self._data: dict[str, Any] = dict(DEFAULTS)
        self._observers: list[Callable[[str, Any], None]] = []
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as handle:
                stored = json.load(handle)
        except FileNotFoundError:
            return
        except (json.JSONDecodeError, OSError) as exc:
            print(f"archclip: config ilegível ({exc}), usando padrões")
            return
        if isinstance(stored, dict):
            # Só aceita chaves conhecidas, para config antiga não injetar lixo.
            for key, value in stored.items():
                if key in DEFAULTS:
                    self._data[key] = value

    def save(self) -> None:
        ensure_dirs()
        payload = json.dumps(self._data, indent=2, ensure_ascii=False)
        directory = self.path.parent
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory, delete=False, suffix=".tmp"
        )
        try:
            with handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(handle.name, self.path)
            harden(self.path, FILE_MODE)
        except OSError as exc:
            print(f"archclip: falha ao gravar config: {exc}")
            try:
                os.unlink(handle.name)
            except OSError:
                pass

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any, *, save: bool = True) -> None:
        if self._data.get(key) == value:
            return
        self._data[key] = value
        if save:
            self.save()
        for observer in list(self._observers):
            observer(key, value)

    def connect(self, callback: Callable[[str, Any], None]) -> None:
        self._observers.append(callback)

    def __getitem__(self, key: str) -> Any:
        return self.get(key)
