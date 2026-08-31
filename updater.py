"""Проверка и установка обновлений приложения через GitHub Releases."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

APP_VERSION = "1.2.0"
REPOSITORY = "No0N/wow_addon_updater"
RELEASE_API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
ASSET_NAME = "ElvUI_Updater.exe"
USER_AGENT = f"ElvUI-Updater/{APP_VERSION}"
MAX_RELEASE_INFO_BYTES = 1024 * 1024
MAX_UPDATE_BYTES = 100 * 1024 * 1024


class AppUpdate(NamedTuple):
    version: str
    download_url: str
    sha256: str
    size: int
    notes: str
    page_url: str


def _version_key(value: str) -> tuple[int, ...]:
    value = value.strip().removeprefix("v")
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError as exc:
        raise RuntimeError(f"Некорректная версия выпуска: {value}") from exc


def _read_url(url: str, limit: int, timeout: int = 20) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("Файл обновления превышает допустимый размер.")
    return data


def get_available_update() -> AppUpdate | None:
    """Вернуть новый выпуск программы или None, если установлена свежая версия."""
    try:
        release = json.loads(_read_url(RELEASE_API_URL, MAX_RELEASE_INFO_BYTES).decode("utf-8"))
        version = str(release["tag_name"]).strip().removeprefix("v")
        if _version_key(version) <= _version_key(APP_VERSION):
            return None
        asset = next(
            item for item in release["assets"]
            if isinstance(item, dict) and item.get("name") == ASSET_NAME
        )
        digest = str(asset.get("digest") or "")
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise RuntimeError("GitHub не предоставил SHA-256 файла обновления.")
        size = int(asset["size"])
        if size <= 0 or size > MAX_UPDATE_BYTES:
            raise RuntimeError("Некорректный размер файла обновления.")
        return AppUpdate(
            version=version,
            download_url=str(asset["browser_download_url"]),
            sha256=digest.removeprefix("sha256:"),
            size=size,
            notes=str(release.get("body") or ""),
            page_url=str(release.get("html_url") or ""),
        )
    except StopIteration as exc:
        raise RuntimeError(f"В выпуске GitHub не найден {ASSET_NAME}.") from exc
    except (HTTPError, URLError, OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Не удалось проверить обновление программы: {exc}") from exc


def download_update(update: AppUpdate) -> Path:
    """Скачать новый EXE рядом с текущим и проверить размер и SHA-256."""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Самообновление доступно только в собранной версии программы.")
    executable = Path(sys.executable).resolve()
    temporary = executable.with_name(executable.name + ".update.tmp")
    try:
        data = _read_url(update.download_url, MAX_UPDATE_BYTES, timeout=120)
        if len(data) != update.size:
            raise RuntimeError("Размер загруженного обновления не совпал.")
        if hashlib.sha256(data).hexdigest() != update.sha256:
            raise RuntimeError("SHA-256 загруженного обновления не совпал.")
        temporary.write_bytes(data)
        return temporary
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def launch_replacement(downloaded_file: Path) -> None:
    """Запустить скрытый процесс, который заменит EXE после закрытия приложения."""
    executable = Path(sys.executable).resolve()

    def ps_quote(path: Path) -> str:
        return "'" + str(path).replace("'", "''") + "'"

    command = (
        f"$source={ps_quote(downloaded_file.resolve())};"
        f"$target={ps_quote(executable)};"
        "$done=$false;"
        "for($i=0;$i -lt 120 -and -not $done;$i++){"
        "try{Move-Item -LiteralPath $source -Destination $target -Force -ErrorAction Stop;$done=$true}"
        "catch{Start-Sleep -Milliseconds 500}};"
        "if($done){Start-Process -FilePath $target}"
    )
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        creationflags=creation_flags,
        close_fds=True,
    )
