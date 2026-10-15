#!/usr/bin/env python3
"""Проверенное зеркало production-сборок ClassCodex."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

UPSTREAM = "https://wow-class-codex.s3.us-east-1.amazonaws.com"
CONFIG_PATH = "channels/retail/production/config.json"
PUBLIC_ROOT = Path("/srv/classcodex/public")
KEEP_BUILDS = 3
MAX_CONFIG = 64 * 1024
MAX_MANIFEST = 4 * 1024 * 1024
MAX_FILE = 64 * 1024 * 1024
MAX_FILES = 5000
USER_AGENT = "ClassCodex-Mirror/1.0"


def fetch(url: str, limit: int, timeout: int = 90) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    with urlopen(request, timeout=timeout) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError(f"response too large: {url}")
    return data


def load_object(data: bytes, label: str) -> dict:
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"invalid {label}")
    return value


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def safe_manifest_path(value: object) -> str:
    if not isinstance(value, str) or len(value) > 512 or "\\" in value or "\0" in value:
        raise RuntimeError("invalid manifest path")
    parts = PurePosixPath(value).parts
    if len(parts) < 2 or parts[0] != "ClassCodex" or any(part in ("", ".", "..") for part in parts):
        raise RuntimeError(f"unsafe manifest path: {value}")
    return value


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def sync() -> None:
    config_bytes = fetch(f"{UPSTREAM}/{CONFIG_PATH}", MAX_CONFIG)
    config = load_object(config_bytes, "config")
    if config.get("gameVersionId") != "retail" or config.get("channel") != "production":
        raise RuntimeError("unexpected channel config")

    build_id = str(config["buildId"])
    if not build_id or "/" in build_id or "\\" in build_id or ".." in build_id:
        raise RuntimeError("invalid build id")
    manifest_url = str(config["manifestUrl"])
    expected_manifest_path = f"/builds/retail/{build_id}/manifest.json"
    parsed = urlparse(manifest_url)
    upstream_parsed = urlparse(UPSTREAM)
    if (
        parsed.scheme != "https"
        or parsed.netloc != upstream_parsed.netloc
        or parsed.path != expected_manifest_path
    ):
        raise RuntimeError("invalid manifest URL")

    manifest_digest = str(config["manifestSha256"])
    if not is_sha256(manifest_digest):
        raise RuntimeError("invalid manifest checksum")
    manifest_bytes = fetch(manifest_url, MAX_MANIFEST)
    if hashlib.sha256(manifest_bytes).hexdigest() != manifest_digest:
        raise RuntimeError("manifest checksum mismatch")

    manifest = load_object(manifest_bytes, "manifest")
    addon = manifest.get("addon", {})
    build = manifest.get("build", {})
    if addon.get("id") != "class-codex" or addon.get("gameVersionId") != "retail":
        raise RuntimeError("unexpected addon manifest")
    if str(build.get("id")) != build_id:
        raise RuntimeError("manifest build mismatch")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries or len(entries) > MAX_FILES:
        raise RuntimeError("invalid file list")

    checked: list[tuple[str, int, str]] = []
    for item in entries:
        if not isinstance(item, dict):
            raise RuntimeError("invalid file entry")
        relative = safe_manifest_path(item.get("path"))
        size = int(item.get("size"))
        digest = item.get("sha256")
        if size < 0 or size > MAX_FILE or not is_sha256(digest):
            raise RuntimeError(f"invalid file metadata: {relative}")
        checked.append((relative, size, str(digest)))

    builds_root = PUBLIC_ROOT / "builds" / "retail"
    final_build = builds_root / build_id
    complete_marker = final_build / ".complete"
    if not complete_marker.is_file() or complete_marker.read_text().strip() != manifest_digest:
        staging = builds_root / f".{build_id}.staging"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)

        def download_file(entry: tuple[str, int, str]) -> None:
            relative, size, digest = entry
            encoded = "/".join(quote(part, safe="") for part in PurePosixPath(relative).parts)
            data = fetch(f"{UPSTREAM}/builds/retail/{build_id}/{encoded}", min(MAX_FILE, size + 1))
            if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                raise RuntimeError(f"file verification failed: {relative}")
            destination = staging / Path(*PurePosixPath(relative).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)

        try:
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(download_file, checked))
            (staging / "manifest.json").write_bytes(manifest_bytes)
            (staging / ".complete").write_text(manifest_digest + "\n")
            if final_build.exists():
                shutil.rmtree(final_build)
            os.replace(staging, final_build)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    atomic_write(PUBLIC_ROOT / CONFIG_PATH, config_bytes)
    health = {
        "status": "ok",
        "buildId": build_id,
        "sequence": int(config["sequence"]),
        "addonVersion": str(addon.get("tocVersion", "")),
        "syncedAt": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write(PUBLIC_ROOT / "health.json", json.dumps(health, indent=2).encode() + b"\n")

    builds = sorted(
        (path for path in builds_root.iterdir() if path.is_dir() and not path.name.startswith(".")),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for obsolete in builds[KEEP_BUILDS:]:
        shutil.rmtree(obsolete)

    print(f"mirrored ClassCodex {addon.get('tocVersion')} build {build_id} ({len(checked)} files)")


if __name__ == "__main__":
    sync()
