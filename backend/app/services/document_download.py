from __future__ import annotations

import mimetypes
import re
import zipfile
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from app.services.object_storage import ObjectStorage, is_storage_uri

_UNSAFE_NAME_RE = re.compile(r"[\\/]+")
_ARCHIVE_SLUG_RE = re.compile(r"[^\w]+", re.UNICODE)


def safe_download_name(file_name: str, fallback: str = "document") -> str:
    name = _UNSAFE_NAME_RE.sub("-", Path(file_name).name).strip()
    return name or fallback


def unique_entry_names(file_names: list[str]) -> list[str]:
    used: set[str] = set()
    unique: list[str] = []
    for raw in file_names:
        base = safe_download_name(raw)
        candidate = base
        stem = Path(base).stem or "document"
        suffix = Path(base).suffix
        index = 2
        while candidate.lower() in used:
            candidate = f"{stem}-{index}{suffix}"
            index += 1
        used.add(candidate.lower())
        unique.append(candidate)
    return unique


def archive_filename(bucket_name: str) -> str:
    slug = _ARCHIVE_SLUG_RE.sub("-", bucket_name.strip()).strip("-").lower()
    slug = slug or "bucket"
    return f"{slug}-documents.zip"


def guess_media_type(file_name: str) -> str:
    media_type, _encoding = mimetypes.guess_type(file_name)
    return media_type or "application/octet-stream"


def content_disposition(file_name: str) -> str:
    ascii_name = (
        file_name.encode("ascii", "ignore").decode("ascii").strip() or "download"
    )
    ascii_name = ascii_name.replace('"', "")
    encoded = quote(file_name)
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded}'


def build_zip_bytes(files: list[tuple[str, bytes]]) -> bytes:
    names = unique_entry_names([name for name, _payload in files])
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, (_original, payload) in zip(names, files, strict=True):
            archive.writestr(name, payload)
    return buffer.getvalue()


def read_ref_bytes(storage: ObjectStorage, ref: str) -> bytes:
    if not ref.strip():
        raise FileNotFoundError("empty source_path")
    if is_storage_uri(ref):
        return storage.get(ref)
    path = Path(ref)
    if path.is_file():
        return path.read_bytes()
    if storage.exists(ref):
        return storage.get(ref)
    raise FileNotFoundError(ref)
