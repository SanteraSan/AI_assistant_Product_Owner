from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.buckets import create_bucket_router


@dataclass
class _FakeBucket:
    id: str
    tenant_id: str
    name: str
    description: str
    status: str = "ready"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class _FakeDocument:
    id: str
    tenant_id: str
    bucket_id: str
    file_name: str
    source_type: str
    source_path: str
    status: str = "uploaded"
    size_bytes: int = 0
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class _FakeBucketService:
    def __init__(self) -> None:
        self.bucket = _FakeBucket(
            id="bucket-1",
            tenant_id="tenant-a",
            name="Demo bucket",
            description="Demo description",
        )
        self.document: _FakeDocument | None = None

    async def list_buckets(self, *, tenant_id: str):
        assert tenant_id == "tenant-a"
        return [(self.bucket, 1 if self.document else 0)]

    async def create_bucket(self, *, tenant_id: str, name: str, description: str, owner_user_id: str | None):
        assert tenant_id == "tenant-a"
        assert owner_user_id == "user-a"
        self.bucket = _FakeBucket(
            id="bucket-created",
            tenant_id=tenant_id,
            name=name,
            description=description,
        )
        return self.bucket

    async def update_bucket(self, *, tenant_id: str, bucket_id: str, name: str | None, description: str | None):
        assert tenant_id == "tenant-a"
        if bucket_id != self.bucket.id:
            return None
        if name is not None:
            self.bucket.name = name
        if description is not None:
            self.bucket.description = description
        return self.bucket

    async def list_documents(self, *, tenant_id: str, bucket_id: str):
        assert tenant_id == "tenant-a"
        if bucket_id != self.bucket.id:
            return None
        return [self.document] if self.document else []

    async def get_document(self, *, tenant_id: str, document_id: str):
        assert tenant_id == "tenant-a"
        if self.document is None or self.document.id != document_id:
            return None
        return self.document

    async def save_uploaded_document(
        self,
        *,
        tenant_id: str,
        bucket_id: str,
        file_name: str,
        content: bytes,
        content_type: str | None,
    ):
        assert tenant_id == "tenant-a"
        assert bucket_id == self.bucket.id
        assert content_type == "text/plain"
        self.document = _FakeDocument(
            id="document-1",
            tenant_id=tenant_id,
            bucket_id=bucket_id,
            file_name=file_name,
            source_type="txt",
            source_path="/tmp/document-1.txt",
            size_bytes=len(content),
        )
        return self.document


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(
        create_bucket_router(
            bucket_service=_FakeBucketService(),  # type: ignore[arg-type]
            default_tenant_id="tenant-a",
        )
    )
    return TestClient(app)


def test_list_buckets_uses_tenant_header() -> None:
    client = _client()

    response = client.get("/buckets", headers={"X-Tenant-ID": "tenant-a"})

    assert response.status_code == 200
    assert response.json()[0]["id"] == "bucket-1"
    assert response.json()[0]["document_count"] == 0


def test_create_bucket_uses_mock_user_header() -> None:
    client = _client()

    response = client.post(
        "/buckets",
        headers={"X-Tenant-ID": "tenant-a", "X-User-ID": "user-a"},
        json={"name": "New bucket", "description": "New description"},
    )

    assert response.status_code == 201
    assert response.json()["name"] == "New bucket"


def test_upload_document_accepts_raw_body() -> None:
    client = _client()

    response = client.post(
        "/buckets/bucket-1/documents/upload",
        content=b"hello",
        headers={
            "Content-Type": "text/plain",
            "X-File-Name": "notes.txt",
            "X-Tenant-ID": "tenant-a",
        },
    )

    assert response.status_code == 201
    assert response.json()["file_name"] == "notes.txt"
    assert response.json()["size_bytes"] == 5
