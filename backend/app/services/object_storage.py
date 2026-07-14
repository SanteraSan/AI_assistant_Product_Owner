"""Object storage for uploaded documents (local FS or MinIO/S3)."""

from __future__ import annotations

import logging
from pathlib import Path
from shutil import copy2, move
from typing import Protocol

logger = logging.getLogger(__name__)

STORAGE_URI_PREFIX = "storage://"


class ObjectStorage(Protocol):
    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        """Store bytes under key; return durable ref for DocumentAsset.source_path."""

    def get(self, ref: str) -> bytes:
        ...

    def delete(self, ref: str) -> None:
        ...

    def move(self, src_ref: str, dst_key: str) -> str:
        """Move/rename object; return new durable ref."""

    def exists(self, ref: str) -> bool:
        ...

    def materialize(self, ref: str, destination: Path) -> Path:
        """Write object bytes to a local path for parsers/vision."""


def is_storage_uri(ref: str) -> bool:
    return ref.startswith(STORAGE_URI_PREFIX)


def storage_uri(key: str) -> str:
    return f"{STORAGE_URI_PREFIX}{key.lstrip('/')}"


def storage_key_from_ref(ref: str) -> str:
    if is_storage_uri(ref):
        return ref[len(STORAGE_URI_PREFIX) :]
    return ref


def display_name_from_ref(ref: str) -> str:
    key = storage_key_from_ref(ref)
    return Path(key).name or "uploaded-file"


class LocalFilesystemStorage:
    """Default storage: files under upload root; refs are absolute paths (legacy-compatible)."""

    def __init__(self, upload_root: Path) -> None:
        self._upload_root = upload_root
        self._upload_root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        del content_type
        path = self._path_for_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    def get(self, ref: str) -> bytes:
        return self._resolve_path(ref).read_bytes()

    def delete(self, ref: str) -> None:
        path = self._resolve_path(ref)
        path.unlink(missing_ok=True)

    def move(self, src_ref: str, dst_key: str) -> str:
        src = self._resolve_path(src_ref)
        dst = self._path_for_key(dst_key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        move(str(src), str(dst))
        return str(dst)

    def exists(self, ref: str) -> bool:
        return self._resolve_path(ref).is_file()

    def materialize(self, ref: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        src = self._resolve_path(ref)
        if src.resolve() != destination.resolve():
            copy2(src, destination)
        return destination

    def _path_for_key(self, key: str) -> Path:
        return self._upload_root / key.lstrip("/")

    def _resolve_path(self, ref: str) -> Path:
        if is_storage_uri(ref):
            return self._path_for_key(storage_key_from_ref(ref))
        return Path(ref)


class S3CompatibleStorage:
    """MinIO / S3-compatible storage; refs are storage://{key}."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "us-east-1",
    ) -> None:
        import boto3
        from botocore.client import Config

        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(signature_version="s3v4"),
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError

        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self._bucket)
            logger.info("Created object storage bucket %s", self._bucket)

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        normalized = key.lstrip("/")
        extra: dict[str, str] = {}
        if content_type:
            extra["ContentType"] = content_type
        self._client.put_object(
            Bucket=self._bucket,
            Key=normalized,
            Body=data,
            **extra,
        )
        return storage_uri(normalized)

    def get(self, ref: str) -> bytes:
        key = storage_key_from_ref(ref)
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()

    def delete(self, ref: str) -> None:
        from botocore.exceptions import ClientError

        key = storage_key_from_ref(ref)
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except ClientError:
            logger.warning("Failed to delete object key=%s", key, exc_info=True)

    def move(self, src_ref: str, dst_key: str) -> str:
        src_key = storage_key_from_ref(src_ref)
        dst = dst_key.lstrip("/")
        self._client.copy_object(
            Bucket=self._bucket,
            CopySource={"Bucket": self._bucket, "Key": src_key},
            Key=dst,
        )
        self.delete(src_ref)
        return storage_uri(dst)

    def exists(self, ref: str) -> bool:
        from botocore.exceptions import ClientError

        key = storage_key_from_ref(ref)
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False

    def materialize(self, ref: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.get(ref))
        return destination


def resolve_upload_root(raw_data_dir: str) -> Path:
    raw_path = Path(raw_data_dir)
    if not raw_path.is_absolute():
        backend_root = Path(__file__).resolve().parents[2]
        raw_path = (backend_root / raw_path).resolve()
    return raw_path / "uploads"


def build_object_storage(
    *,
    enabled: bool,
    upload_root: Path,
    endpoint_url: str,
    access_key: str,
    secret_key: str,
    bucket: str,
    region: str,
) -> LocalFilesystemStorage | S3CompatibleStorage:
    if not enabled:
        return LocalFilesystemStorage(upload_root)
    return S3CompatibleStorage(
        endpoint_url=endpoint_url,
        access_key=access_key,
        secret_key=secret_key,
        bucket=bucket,
        region=region,
    )
