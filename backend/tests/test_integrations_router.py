from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.integrations import create_integrations_router
from tests.auth_helpers import auth_headers


@dataclass
class _FakeBucket:
    id: str = "bucket-int-1"
    name: str = "n8n Integrations"


@dataclass
class _FakeDocument:
    id: str = "doc-1"
    file_name: str = "brief.txt"
    status: str = "indexing"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class _FakeIngestService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def ingest_bytes(self, **kwargs):
        self.calls.append(kwargs)
        if not kwargs.get("content"):
            raise ValueError("Uploaded file is empty.")
        return _FakeDocument(), ["job-1"], _FakeBucket(), {
            "source": "n8n",
            "channel": kwargs.get("channel", "disk"),
        }


class _FakeSyncService:
    async def sync_tenant(self, *, tenant_id: str):
        return {
            "tenant_id": tenant_id,
            "customers_upserted": 3,
            "tickets_upserted": 4,
            "status": "ok",
            "synced_at": datetime.now(UTC),
        }


def _app(ingest=_FakeIngestService(), sync=_FakeSyncService()) -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_integrations_router(
            integration_ingest_service=ingest,
            external_db_sync_service=sync,
            document_indexing_service=None,
        )
    )
    return app


def test_ingest_requires_auth() -> None:
    client = TestClient(_app())
    response = client.post("/integrations/ingest", content=b"hello")
    assert response.status_code == 401


def test_ingest_returns_document_and_jobs() -> None:
    ingest = _FakeIngestService()
    client = TestClient(_app(ingest=ingest))
    response = client.post(
        "/integrations/ingest",
        content=b"hello from n8n",
        headers={
            **auth_headers(sub="n8n-integration", roles=["admin"]),
            "X-File-Name": "brief.txt",
            "X-Integration-Channel": "disk",
            "Content-Type": "text/plain",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["document_id"] == "doc-1"
    assert payload["bucket_id"] == "bucket-int-1"
    assert payload["indexing_job_ids"] == ["job-1"]
    assert payload["metadata"]["source"] == "n8n"
    assert ingest.calls[0]["file_name"] == "brief.txt"
    assert ingest.calls[0]["channel"] == "disk"


def test_sync_external_db_ok_for_analyst() -> None:
    client = TestClient(_app())
    response = client.post(
        "/integrations/sync-external-db",
        headers=auth_headers(sub="analyst-1", roles=["analyst"]),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["customers_upserted"] == 3
    assert payload["tickets_upserted"] == 4
    assert payload["status"] == "ok"


def test_sync_external_db_forbidden_for_viewer() -> None:
    client = TestClient(_app())
    response = client.post(
        "/integrations/sync-external-db",
        headers=auth_headers(sub="viewer-1", roles=["viewer"]),
    )
    assert response.status_code == 403
