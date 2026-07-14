from datetime import datetime

from pydantic import BaseModel, Field


class IntegrationIngestResponse(BaseModel):
    document_id: str
    bucket_id: str
    file_name: str
    status: str
    indexing_job_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class ExternalDbSyncResponse(BaseModel):
    tenant_id: str
    customers_upserted: int
    tickets_upserted: int
    status: str = "ok"
    error: str | None = None
    synced_at: datetime
