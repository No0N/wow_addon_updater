"""
Сохранение и загрузка настроек: пути к WoW и чекбоксы обновления.
Файл конфига хранится рядом с exe или в текущей директории.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

CONFIG_FILENAME = "elvui_updater_config.json"


def _config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / CONFIG_FILENAME
    return Path(__file__).resolve().parent / CONFIG_FILENAME


DEFAULT_CONFIG: dict[str, Any] = {
    "path_retail": "",       # WoW актуал (retail)
    "path_classic": "",     # WoW классик
    "update_retail": True,
    "update_classic": False,
    "update_classcodex": True,
    "classcodex_build_id": "",
}


def load_config() -> dict[str, Any]:
    """Загрузить конфиг; если файла нет — вернуть значения по умолчанию."""
    path = _config_path()
    if not path.is_file():
        return DEFAULT_CONFIG.copy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        out = DEFAULT_CONFIG.copy()
        for key in out:
            if key in data:
                out[key] = data[key]
        return out
    except (json.JSONDecodeError, OSError):
        return DEFAULT_CONFIG.copy()


def save_config(config: dict[str, Any]) -> None:
    """Сохранить конфиг в файл."""
    path = _config_path()
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
