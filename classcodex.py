"""Проверка и установка ClassCodex из официального канала U.GG."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable, NamedTuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

UGG_CDN_BASE = "https://wow-class-codex.s3.us-east-1.amazonaws.com"
UGG_CHANNEL_CONFIG_URL = f"{UGG_CDN_BASE}/channels/retail/production/config.json"
VERSION_PREFIX = "## Version:"
USER_AGENT = "ElvUI-Updater/1.0"
MAX_CONFIG_BYTES = 64 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_FILE_COUNT = 5000


class ClassCodexInfo(NamedTuple):
    version: str
    last_update: str
    download_url: str
    manifest_sha256: str
    build_id: str
    sequence: int
    files: tuple[tuple[str, int, str], ...]


def _normalize_version(version: str) -> str:
    version = version.strip()
    return version[1:] if version.lower().startswith("v") else version


def _fetch_bytes(url: str, limit: int, timeout: int = 20) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    with urlopen(request, timeout=timeout) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError(f"Ответ U.GG превышает допустимый размер: {url}")
    return data


def _load_json(data: bytes, label: str) -> dict:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"U.GG вернул некорректный {label}.") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"U.GG вернул некорректный {label}.")
    return value


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _validate_ugg_url(url: str, expected_path: str) -> None:
    parsed = urlparse(url)
    base = urlparse(UGG_CDN_BASE)
    if parsed.scheme != "https" or parsed.netloc != base.netloc or parsed.path != expected_path:
        raise RuntimeError("U.GG вернул недопустимую ссылку на манифест ClassCodex.")


def get_classcodex_info() -> ClassCodexInfo:
    """Получить текущую production-сборку ClassCodex для Retail с U.GG."""
    try:
        config = _load_json(_fetch_bytes(UGG_CHANNEL_CONFIG_URL, MAX_CONFIG_BYTES), "config.json")
        if config.get("gameVersionId") != "retail" or config.get("channel") != "production":
            raise RuntimeError("U.GG вернул сборку не для Retail production.")
        build_id = str(config["buildId"])
        sequence = int(config["sequence"])
        manifest_url = str(config["manifestUrl"])
        manifest_sha256 = str(config["manifestSha256"])
        _validate_ugg_url(manifest_url, f"/builds/retail/{build_id}/manifest.json")
        if not _is_sha256(manifest_sha256):
            raise RuntimeError("U.GG вернул некорректную контрольную сумму манифеста.")

        manifest_bytes = _fetch_bytes(manifest_url, MAX_MANIFEST_BYTES)
        if hashlib.sha256(manifest_bytes).hexdigest() != manifest_sha256:
            raise RuntimeError("Контрольная сумма манифеста ClassCodex не совпала.")
        manifest = _load_json(manifest_bytes, "manifest.json")
        addon = manifest["addon"]
        build = manifest["build"]
        if addon.get("id") != "class-codex" or addon.get("gameVersionId") != "retail":
            raise RuntimeError("Манифест U.GG относится к другому аддону.")
        if str(build.get("id")) != build_id or int(build.get("sequence")) != sequence:
            raise RuntimeError("Сборка в манифесте U.GG не совпадает с каналом обновления.")
        files = _parse_manifest_files(manifest)
        version = _normalize_version(str(addon["tocVersion"]))
        last_update = str(build.get("createdAt", config.get("publishedAt", "")))
    except (HTTPError, URLError, OSError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Не удалось получить данные ClassCodex с U.GG: {exc}") from exc

    return ClassCodexInfo(version, last_update, manifest_url, manifest_sha256, build_id, sequence, files)


def get_installed_classcodex_version(target_dir: Path) -> str | None:
    """Прочитать ## Version из ClassCodex/ClassCodex.toc."""
    toc_path = _normalize_addons_dir(target_dir) / "ClassCodex" / "ClassCodex.toc"
    if not toc_path.is_file():
        return None
    try:
        lines = toc_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if line.lower().startswith(VERSION_PREFIX.lower()):
            version = _normalize_version(line[len(VERSION_PREFIX):])
            return version or None
    return None


def _validate_manifest_path(value: object) -> str:
    if not isinstance(value, str) or len(value) > 512 or "\\" in value or "\0" in value:
        raise RuntimeError("Манифест U.GG содержит некорректный путь файла.")
    parts = PurePosixPath(value).parts
    if len(parts) < 2 or parts[0] != "ClassCodex" or any(part in ("", ".", "..") for part in parts):
        raise RuntimeError(f"Манифест U.GG содержит небезопасный путь: {value}")
    return value


def _parse_manifest_files(manifest: dict) -> tuple[tuple[str, int, str], ...]:
    files = manifest.get("files")
    if not isinstance(files, list) or not files or len(files) > MAX_FILE_COUNT:
        raise RuntimeError("Манифест U.GG содержит некорректный список файлов.")
    checked: list[tuple[str, int, str]] = []
    for item in files:
        if not isinstance(item, dict):
            raise RuntimeError("Манифест U.GG содержит некорректную запись файла.")
        path = _validate_manifest_path(item.get("path"))
        size = int(item.get("size"))
        digest = item.get("sha256")
        if size < 0 or size > MAX_FILE_BYTES or not _is_sha256(digest):
            raise RuntimeError(f"Некорректные данные файла в манифесте: {path}")
        checked.append((path, size, str(digest)))
    return tuple(checked)


def is_installed_classcodex_current(target_dir: Path, info: ClassCodexInfo) -> bool:
    """Сверить установленную сборку со всеми файлами манифеста U.GG."""
    addons_dir = _normalize_addons_dir(target_dir)
    for relative, expected_size, expected_digest in info.files:
        path = addons_dir / Path(*PurePosixPath(relative).parts)
        try:
            if not path.is_file() or path.stat().st_size != expected_size:
                return False
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return False
        if digest != expected_digest:
            return False
    return True


def _files_requiring_update(
    target_dir: Path,
    files: tuple[tuple[str, int, str], ...],
) -> tuple[tuple[str, int, str], ...]:
    """Вернуть отсутствующие или отличающиеся от манифеста файлы."""
    addons_dir = _normalize_addons_dir(target_dir)
    outdated: list[tuple[str, int, str]] = []
    for item in files:
        relative, expected_size, expected_digest = item
        path = addons_dir / Path(*PurePosixPath(relative).parts)
        try:
            matches = (
                path.is_file()
                and path.stat().st_size == expected_size
                and hashlib.sha256(path.read_bytes()).hexdigest() == expected_digest
            )
        except OSError:
            matches = False
        if not matches:
            outdated.append(item)
    return tuple(outdated)


def download_classcodex_zip(
    info: ClassCodexInfo,
    progress_callback: Callable[[int, int], None] | None = None,
    target_dir: Path | None = None,
) -> bytes:
    """Скачать изменившиеся файлы U.GG, проверить SHA-256 и собрать локальный ZIP."""
    try:
        manifest_bytes = _fetch_bytes(info.download_url, MAX_MANIFEST_BYTES)
        if hashlib.sha256(manifest_bytes).hexdigest() != info.manifest_sha256:
            raise RuntimeError("Контрольная сумма манифеста ClassCodex не совпала.")
        manifest = _load_json(manifest_bytes, "manifest.json")
        checked_files = _parse_manifest_files(manifest)
        files_to_download = (
            _files_requiring_update(target_dir, checked_files)
            if target_dir is not None
            else checked_files
        )

        def fetch_file(item: tuple[str, int, str]) -> tuple[str, bytes]:
            path, size, digest = item
            encoded_path = "/".join(quote(part, safe="") for part in PurePosixPath(path).parts)
            url = f"{UGG_CDN_BASE}/builds/retail/{info.build_id}/{encoded_path}"
            data = _fetch_bytes(url, min(MAX_FILE_BYTES, size + 1), timeout=60)
            if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                raise RuntimeError(f"Проверка загруженного файла не пройдена: {path}")
            return path, data

        downloaded: list[tuple[str, bytes]] = []
        total = len(files_to_download)
        for index, item in enumerate(files_to_download, start=1):
            downloaded.append(fetch_file(item))
            if progress_callback:
                progress_callback(index, total)

        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, data in downloaded:
                archive.writestr(path, data)
        return output.getvalue()
    except (HTTPError, URLError, OSError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Ошибка скачивания ClassCodex с U.GG: {exc}") from exc


def _normalize_addons_dir(target_dir: Path) -> Path:
    path = target_dir.resolve()
    if path.is_file():
        path = path.parent
    if path.name.lower() == "classcodex":
        path = path.parent
    if path.name.lower() != "addons":
        path = path / "Interface" / "AddOns"
    return path.resolve()


def extract_classcodex_to_folder(
    zip_data: bytes,
    target_dir: Path,
    *,
    allow_partial: bool = False,
) -> None:
    """Безопасно распаковать проверенную сборку ClassCodex в Interface/AddOns."""
    addons_dir = _normalize_addons_dir(target_dir)
    addons_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(zip_data)) as archive:
        files = [name.replace("\\", "/") for name in archive.namelist() if not name.endswith("/")]
        if not allow_partial and "ClassCodex/ClassCodex.toc" not in files:
            raise RuntimeError("В сборке U.GG не найден ClassCodex.toc.")
        for name in files:
            safe_name = _validate_manifest_path(name)
            destination = (addons_dir / Path(*PurePosixPath(safe_name).parts)).resolve()
            if addons_dir not in destination.parents:
                raise RuntimeError("Сборка ClassCodex пытается записать файл вне AddOns.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(name))
