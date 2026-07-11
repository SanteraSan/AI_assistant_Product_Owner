from datetime import datetime

from pydantic import BaseModel, Field


class BucketCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)


class BucketUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class BucketResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: str
    status: str
    document_count: int
    created_at: datetime
    updated_at: datetime


class DocumentResponse(BaseModel):
    id: str
    tenant_id: str
    bucket_id: str
    file_name: str
    source_type: str
    source_path: str
    status: str
    size_bytes: int
    error: str | None = None
    created_at: datetime
    updated_at: datetime
