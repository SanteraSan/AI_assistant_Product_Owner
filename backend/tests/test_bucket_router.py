from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.buckets import create_bucket_router
from app.services.bucket_service import BucketDownloadFile, BucketDownloadResult, DocumentDeleteResult
from tests.auth_helpers import auth_headers


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
    title: str
    file_name: str
    source_type: str
    source_path: str
    owner_user_id: str | None = "user-a"
    status: str = "uploaded"
    visibility: str = "private"
    allowed_roles: list[str] = field(default_factory=list)
    size_bytes: int = 0
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class _FakeStagedUpload:
    id: str
    tenant_id: str
    owner_user_id: str | None
    original_file_name: str
    source_type: str
    source_path: str
    status: str = "staged"
    size_bytes: int = 0
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class _FakeBucketDocument:
    indexing_status: str = "indexed"
    indexing_error: str | None = None


class _FakeBucketService:
    def __init__(self) -> None:
        self.bucket = _FakeBucket(
            id="bucket-1",
            tenant_id="tenant-a",
            name="Demo bucket",
            description="Demo description",
        )
        self.document: _FakeDocument | None = None
        self.bucket_link = _FakeBucketDocument()
        self.staged_upload: _FakeStagedUpload | None = None
        self.download_files: dict[str, tuple[str, bytes]] = {}
        self.forbidden_download_ids: set[str] = set()

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

    async def list_documents(self, *, user, bucket_id: str):
        assert user.tenant_id == "tenant-a"
        assert user.user_id == "user-a"
        if bucket_id != self.bucket.id:
            return None
        return [(self.document, self.bucket_link)] if self.document else []

    async def collect_bucket_download(self, *, user, bucket_id: str, document_ids: list[str]):
        assert user.tenant_id == "tenant-a"
        if bucket_id != self.bucket.id:
            return BucketDownloadResult(not_found=True)
        files: list[BucketDownloadFile] = []
        for document_id in document_ids:
            if document_id in self.forbidden_download_ids:
                return BucketDownloadResult(forbidden=True)
            item = self.download_files.get(document_id)
            if item is None:
                return BucketDownloadResult(not_found=True)
            file_name, content = item
            files.append(
                BucketDownloadFile(
                    document_id=document_id,
                    file_name=file_name,
                    content=content,
                )
            )
        return BucketDownloadResult(bucket_name=self.bucket.name, files=tuple(files))

    async def get_document(self, *, user, document_id: str):
        assert user.tenant_id == "tenant-a"
        if self.document is None or self.document.id != document_id:
            return None
        return self.document

    async def list_my_documents(self, *, user):
        assert user.tenant_id == "tenant-a"
        return [self.document] if self.document else []

    async def list_available_documents(self, *, user):
        assert user.tenant_id == "tenant-a"
        assert "analyst" in user.roles
        return [self.document] if self.document else []

    async def add_document_to_bucket(self, *, user, bucket_id: str, document_id: str):
        assert user.tenant_id == "tenant-a"
        assert user.user_id == "user-a"
        if bucket_id != self.bucket.id or self.document is None or self.document.id != document_id:
            return None
        return self.document

    async def remove_document_from_bucket(self, *, user, bucket_id: str, document_id: str):
        assert user.tenant_id == "tenant-a"
        return bucket_id == self.bucket.id

    async def delete_document(self, *, user, document_id: str):
        assert user.tenant_id == "tenant-a"
        assert user.user_id == "user-a"
        if document_id == "in-use-document":
            return DocumentDeleteResult(
                deleted=False,
                in_use_buckets=[("bucket-3", "Bucket 3"), ("bucket-5", "Bucket 5")],
            )
        if self.document is None or self.document.id != document_id:
            return DocumentDeleteResult(deleted=False, not_found=True)
        self.document = None
        return DocumentDeleteResult(deleted=True)

    async def delete_bucket(self, *, tenant_id: str, bucket_id: str):
        assert tenant_id == "tenant-a"
        if bucket_id != self.bucket.id:
            return False
        self.bucket = None  # type: ignore[assignment]
        return True

    async def retry_document_indexing(self, *, user, document_id: str, bucket_id: str | None = None):
        assert user.tenant_id == "tenant-a"
        assert user.user_id == "user-a"
        if self.document is None or self.document.id != document_id:
            return None
        self.document.status = "indexing"
        self.document.error = None
        return self.document, "job-retry"

    async def stage_uploaded_document(self, *, user, file_name: str, content: bytes, content_type: str | None):
        assert user.tenant_id == "tenant-a"
        assert user.user_id == "user-a"
        assert content_type == "text/plain"
        self.staged_upload = _FakeStagedUpload(
            id="stage-1",
            tenant_id=user.tenant_id,
            owner_user_id=user.user_id,
            original_file_name=file_name,
            source_type="txt",
            source_path="/tmp/stage-1.txt",
            size_bytes=len(content),
        )
        return self.staged_upload

    async def cancel_staged_upload(self, *, user, upload_id: str):
        assert user.tenant_id == "tenant-a"
        if self.staged_upload is None or self.staged_upload.id != upload_id:
            return False
        self.staged_upload.status = "cancelled"
        return True

    async def commit_bucket_documents(
        self,
        *,
        user,
        bucket_id: str,
        staged_upload_ids: list[str],
        existing_document_ids: list[str],
        removed_document_ids: list[str],
        visibility: str = "private",
        allowed_roles: list[str] | None = None,
    ):
        assert user.tenant_id == "tenant-a"
        assert bucket_id == self.bucket.id
        assert staged_upload_ids == ["stage-1"]
        assert existing_document_ids == []
        assert removed_document_ids == ["old-document"]
        assert visibility == "private"
        self.document = _FakeDocument(
            id="document-committed",
            tenant_id=user.tenant_id,
            title="notes.txt",
            file_name="notes.txt",
            source_type="txt",
            source_path="/tmp/document-committed.txt",
            status="indexing",
            visibility=visibility,
            allowed_roles=allowed_roles or [],
            size_bytes=5,
        )
        return [self.document], ["job-1"]

    async def commit_personal_documents(
        self,
        *,
        user,
        staged_upload_ids: list[str],
        visibility: str = "private",
        allowed_roles: list[str] | None = None,
    ):
        assert user.tenant_id == "tenant-a"
        assert staged_upload_ids == ["stage-1"]
        assert visibility == "private"
        self.document = _FakeDocument(
            id="document-personal",
            tenant_id=user.tenant_id,
            title="notes.txt",
            file_name="notes.txt",
            source_type="txt",
            source_path="/tmp/document-personal.txt",
            status="indexing",
            visibility=visibility,
            allowed_roles=allowed_roles or [],
            size_bytes=5,
        )
        return [self.document], ["job-personal"]

    async def save_uploaded_document(
        self,
        *,
        user,
        bucket_id: str | None,
        file_name: str,
        content: bytes,
        content_type: str | None,
        visibility: str = "private",
        allowed_roles: list[str] | None = None,
    ):
        assert user.tenant_id == "tenant-a"
        assert user.user_id == "user-a"
        assert bucket_id == self.bucket.id
        assert content_type == "text/plain"
        self.document = _FakeDocument(
            id="document-1",
            tenant_id=user.tenant_id,
            title=file_name,
            file_name=file_name,
            source_type="txt",
            source_path="/tmp/document-1.txt",
            visibility=visibility,
            allowed_roles=allowed_roles or [],
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

    response = client.get("/buckets", headers=auth_headers(sub="user-a", tenant_id="tenant-a", roles=["analyst"]))

    assert response.status_code == 200
    assert response.json()[0]["id"] == "bucket-1"
    assert response.json()[0]["document_count"] == 0


def test_create_bucket_uses_mock_user_header() -> None:
    client = _client()

    response = client.post(
        "/buckets",
        headers=auth_headers(sub="user-a", tenant_id="tenant-a", roles=["analyst"]),
        json={"name": "New bucket", "description": "New description"},
    )

    assert response.status_code == 201
    assert response.json()["name"] == "New bucket"


def test_upload_document_accepts_raw_body() -> None:
    client = _client()

    response = client.post(
        "/buckets/bucket-1/documents/upload",
        content=b"hello",
        headers={**auth_headers(sub="user-a", tenant_id="tenant-a", roles=["analyst"]), "Content-Type": "text/plain", "X-File-Name": "notes.txt"},
    )

    assert response.status_code == 201
    assert response.json()["file_name"] == "notes.txt"
    assert response.json()["size_bytes"] == 5
    assert response.json()["visibility"] == "private"


def test_list_available_documents_passes_roles_to_service() -> None:
    client = _client()
    client.post(
        "/buckets/bucket-1/documents/upload",
        content=b"hello",
        headers={**auth_headers(sub="user-a", tenant_id="tenant-a", roles=["analyst"]), "Content-Type": "text/plain", "X-File-Name": "notes.txt"},
    )

    response = client.get(
        "/documents/available",
        headers={**auth_headers(sub="user-a", tenant_id="tenant-a", roles=["analyst"])},
    )

    assert response.status_code == 200
    assert response.json()[0]["id"] == "document-1"


def test_add_existing_document_to_bucket() -> None:
    client = _client()
    client.post(
        "/buckets/bucket-1/documents/upload",
        content=b"hello",
        headers={**auth_headers(sub="user-a", tenant_id="tenant-a", roles=["analyst"]), "Content-Type": "text/plain", "X-File-Name": "notes.txt"},
    )

    response = client.post(
        "/buckets/bucket-1/documents/document-1",
        headers={**auth_headers(sub="user-a", tenant_id="tenant-a", roles=["analyst"])},
    )

    assert response.status_code == 201
    assert response.json()["bucket_id"] == "bucket-1"


def test_stage_document_upload_accepts_raw_body() -> None:
    client = _client()

    response = client.post(
        "/documents/stage",
        content=b"hello",
        headers={**auth_headers(sub="user-a", tenant_id="tenant-a", roles=["analyst"]), "Content-Type": "text/plain", "X-File-Name": "notes.txt"},
    )

    assert response.status_code == 201
    assert response.json()["id"] == "stage-1"
    assert response.json()["original_file_name"] == "notes.txt"
    assert response.json()["status"] == "staged"


def test_stage_document_upload_decodes_cyrillic_file_name() -> None:
    client = _client()

    response = client.post(
        "/documents/stage",
        content=b"hello",
        headers={**auth_headers(sub="user-a", tenant_id="tenant-a", roles=["analyst"]), "Content-Type": "text/plain", "X-File-Name": "%D1%82%D0%B5%D1%81%D1%82.txt", "X-File-Name-Encoding": "uri-component"},
    )

    assert response.status_code == 201
    assert response.json()["original_file_name"] == "тест.txt"


def test_cancel_staged_upload() -> None:
    client = _client()
    client.post(
        "/documents/stage",
        content=b"hello",
        headers={**auth_headers(sub="user-a", tenant_id="tenant-a", roles=["analyst"]), "Content-Type": "text/plain", "X-File-Name": "notes.txt"},
    )

    response = client.delete(
        "/documents/stage/stage-1",
        headers={**auth_headers(sub="user-a", tenant_id="tenant-a", roles=["analyst"])},
    )

    assert response.status_code == 204


def test_commit_bucket_documents_returns_indexing_job_ids() -> None:
    client = _client()

    response = client.post(
        "/buckets/bucket-1/documents/-/commit",
        headers={**auth_headers(sub="user-a", tenant_id="tenant-a", roles=["analyst"])},
        json={
            "staged_upload_ids": ["stage-1"],
            "existing_document_ids": [],
            "removed_document_ids": ["old-document"],
            "visibility": "private",
            "allowed_roles": [],
        },
    )

    assert response.status_code == 200
    assert response.json()["documents"][0]["id"] == "document-committed"
    assert response.json()["indexing_job_ids"] == ["job-1"]


def test_commit_personal_documents_returns_document_without_bucket_id() -> None:
    client = _client()

    response = client.post(
        "/documents/-/commit-personal",
        headers={**auth_headers(sub="user-a", tenant_id="tenant-a", roles=["analyst"])},
        json={
            "staged_upload_ids": ["stage-1"],
            "visibility": "private",
            "allowed_roles": [],
        },
    )

    assert response.status_code == 200
    assert response.json()["documents"][0]["id"] == "document-personal"
    assert response.json()["documents"][0]["bucket_id"] is None
    assert response.json()["indexing_job_ids"] == ["job-personal"]


def test_delete_personal_document() -> None:
    app = FastAPI()
    service = _FakeBucketService()
    service.document = _FakeDocument(
        id="document-1",
        tenant_id="tenant-a",
        title="notes.txt",
        file_name="notes.txt",
        source_type="txt",
        source_path="/tmp/notes.txt",
        status="indexed",
    )
    app.include_router(
        create_bucket_router(
            bucket_service=service,  # type: ignore[arg-type]
            default_tenant_id="tenant-a",
        )
    )
    client = TestClient(app)

    response = client.delete(
        "/documents/document-1",
        headers=auth_headers(sub="user-a", tenant_id="tenant-a", roles=["analyst"]),
    )

    assert response.status_code == 204


def test_delete_document_returns_conflict_when_used_in_buckets() -> None:
    client = _client()

    response = client.delete(
        "/documents/in-use-document",
        headers=auth_headers(sub="user-a", tenant_id="tenant-a", roles=["analyst"]),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "document_in_use"
    assert response.json()["detail"]["buckets"][0]["name"] == "Bucket 3"


def test_delete_bucket() -> None:
    client = _client()

    response = client.delete(
        "/buckets/bucket-1",
        headers=auth_headers(sub="user-a", tenant_id="tenant-a", roles=["analyst"]),
    )

    assert response.status_code == 204


def test_retry_document_indexing() -> None:
    app = FastAPI()
    service = _FakeBucketService()
    service.document = _FakeDocument(
        id="document-1",
        tenant_id="tenant-a",
        title="notes.txt",
        file_name="notes.txt",
        source_type="txt",
        source_path="/tmp/notes.txt",
        status="index_failed",
    )
    app.include_router(
        create_bucket_router(
            bucket_service=service,  # type: ignore[arg-type]
            default_tenant_id="tenant-a",
        )
    )
    client = TestClient(app)

    response = client.post(
        "/documents/document-1/retry-indexing",
        headers=auth_headers(sub="user-a", tenant_id="tenant-a", roles=["analyst"]),
    )

    assert response.status_code == 200
    assert response.json()["documents"][0]["status"] == "indexing"
    assert response.json()["indexing_job_ids"] == ["job-retry"]


def test_download_single_bucket_document() -> None:
    app = FastAPI()
    service = _FakeBucketService()
    service.download_files["document-1"] = ("aurora-legal.md", b"legal notes")
    app.include_router(
        create_bucket_router(
            bucket_service=service,  # type: ignore[arg-type]
            default_tenant_id="tenant-a",
        )
    )
    client = TestClient(app)

    response = client.get(
        "/buckets/bucket-1/documents/document-1/download",
        headers=auth_headers(sub="user-a", tenant_id="tenant-a", roles=["analyst"]),
    )

    assert response.status_code == 200
    assert response.content == b"legal notes"
    assert "aurora-legal.md" in response.headers["content-disposition"]


def test_download_multiple_bucket_documents_as_zip() -> None:
    import zipfile
    from io import BytesIO

    app = FastAPI()
    service = _FakeBucketService()
    service.download_files = {
        "document-1": ("aurora-legal.md", b"legal"),
        "document-2": ("aurora-playbook.md", b"playbook"),
    }
    app.include_router(
        create_bucket_router(
            bucket_service=service,  # type: ignore[arg-type]
            default_tenant_id="tenant-a",
        )
    )
    client = TestClient(app)

    response = client.post(
        "/buckets/bucket-1/documents/download",
        headers=auth_headers(sub="user-a", tenant_id="tenant-a", roles=["analyst"]),
        json={"document_ids": ["document-1", "document-2"]},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        assert archive.read("aurora-legal.md") == b"legal"
        assert archive.read("aurora-playbook.md") == b"playbook"


def test_download_unknown_document_is_not_found() -> None:
    app = FastAPI()
    app.include_router(
        create_bucket_router(
            bucket_service=_FakeBucketService(),  # type: ignore[arg-type]
            default_tenant_id="tenant-a",
        )
    )
    client = TestClient(app)

    response = client.get(
        "/buckets/bucket-1/documents/missing/download",
        headers=auth_headers(sub="user-a", tenant_id="tenant-a", roles=["analyst"]),
    )

    assert response.status_code == 404


def test_download_forbidden_document_is_denied() -> None:
    app = FastAPI()
    service = _FakeBucketService()
    service.download_files["document-1"] = ("secret.md", b"nope")
    service.forbidden_download_ids.add("document-1")
    app.include_router(
        create_bucket_router(
            bucket_service=service,  # type: ignore[arg-type]
            default_tenant_id="tenant-a",
        )
    )
    client = TestClient(app)

    response = client.post(
        "/buckets/bucket-1/documents/download",
        headers=auth_headers(sub="user-a", tenant_id="tenant-a", roles=["analyst"]),
        json={"document_ids": ["document-1"]},
    )

    assert response.status_code == 403
