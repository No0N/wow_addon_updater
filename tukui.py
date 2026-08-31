"""
Работа с Tukui API: получение версии ElvUI и скачивание архива.
API: https://api.tukui.org/v1/addons
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import NamedTuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ADDONS_API = "https://api.tukui.org/v1/addons"
ELVUI_SLUG = "elvui"


class ElvUIInfo(NamedTuple):
    """Информация о версии ElvUI с сайта."""
    version: str
    last_update: str
    download_url: str
    directories: list[str]


def get_elvui_info() -> ElvUIInfo | None:
    """
    Получить текущую версию и ссылку на скачивание ElvUI из API Tukui.
    """
    try:
        request = Request(ADDONS_API, headers={"User-Agent": "ElvUI-Updater/1.0"})
        with urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, ValueError, KeyError) as e:
        raise RuntimeError(f"Не удалось получить данные Tukui: {e}") from e

    for addon in data:
        if isinstance(addon, dict) and addon.get("slug") == ELVUI_SLUG:
            return ElvUIInfo(
                version=str(addon["version"]),
                last_update=str(addon.get("last_update", "")),
                download_url=addon["url"],
                directories=addon.get("directories", ["ElvUI", "ElvUI_Libraries", "ElvUI_Options"]),
            )
    raise RuntimeError("ElvUI не найден в ответе API Tukui.")


def download_elvui_zip(download_url: str) -> bytes:
    """Скачать архив ElvUI по ссылке из API. Возвращает содержимое zip."""
    try:
        request = Request(download_url, headers={"User-Agent": "ElvUI-Updater/1.0"})
        with urlopen(request, timeout=60) as response:
            return response.read()
    except (HTTPError, URLError, OSError) as e:
        raise RuntimeError(f"Ошибка скачивания: {e}") from e


# Имена .toc главного аддона ElvUI (версия во всех одна)
ELVUI_TOC_NAMES = ("ElvUI_Mainline.toc", "ElvUI_Wrath.toc", "ElvUI_TBC.toc", "ElvUI_Mists.toc", "ElvUI_Vanilla.toc")
VERSION_PREFIX = "## Version:"


def get_installed_elvui_version(target_dir: Path) -> str | None:
    """
    Прочитать установленную версию ElvUI из папки AddOns.
    Версия берётся из ElvUI/ElvUI_*.toc (строка ## Version: v15.08).
    target_dir — путь к AddOns или к корню игры.
    Возвращает нормализованную версию (например "15.08") или None, если не найдено.
    """
    addons_dir = _normalize_addons_dir(target_dir)
    elvui_dir = addons_dir / "ElvUI"
    if not elvui_dir.is_dir():
        return None
    for toc_name in ELVUI_TOC_NAMES:
        toc_path = elvui_dir / toc_name
        if not toc_path.is_file():
            continue
        try:
            text = toc_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if line.startswith(VERSION_PREFIX):
                raw = line[len(VERSION_PREFIX):].strip()
                # убрать префикс "v" если есть: v15.08 -> 15.08
                if raw.startswith("v"):
                    raw = raw[1:]
                if raw:
                    return raw
        break
    return None


def _normalize_addons_dir(target_dir: Path) -> Path:
    """Привести путь к папке Interface/AddOns."""
    p = target_dir.resolve()
    if p.is_file():
        p = p.parent
    if p.name.lower() != "addons":
        p = p / "Interface" / "AddOns"
    return p.resolve()


def extract_elvui_to_folder(zip_data: bytes, target_dir: Path) -> None:
    """
    Распаковать архив ElvUI в папку AddOns с заменой файлов.
    В архиве: корневые папки ElvUI, ElvUI_Libraries, ElvUI_Options
    или одна обёртка вида ElvUI-15.08/ с ними внутри.
    target_dir — путь к папке AddOns или к корню игры.
    """
    addons_dir = _normalize_addons_dir(target_dir)
    addons_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(zip_data), "r") as zf:
        names = [n.replace("\\", "/") for n in zf.namelist()]
        # Один корневой каталог в архиве (например ElvUI-15.08) — убираем его
        roots = {n.split("/")[0] for n in names if n.strip() and not n.endswith("/")}
        strip_prefix = ""
        if len(roots) == 1:
            single = next(iter(roots))
            if "elvui" in single.lower() and single != "ElvUI" and "ElvUI_Options" not in single:
                strip_prefix = single + "/"
        elif len(roots) >= 2 and "ElvUI" in roots:
            # Уже ElvUI, ElvUI_Options и т.д. на верхнем уровне
            pass
        else:
            strip_prefix = next(iter(roots)) + "/" if roots else ""

        for name in names:
            if name.endswith("/"):
                continue
            rel = name[len(strip_prefix):] if name.startswith(strip_prefix) else name
            if not rel or rel.startswith("/"):
                continue
            dest_path = addons_dir / rel
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(zf.read(name))
