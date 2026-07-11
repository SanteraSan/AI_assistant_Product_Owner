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
    bucket_id: str | None = None
    owner_user_id: str | None = None
    title: str
    file_name: str
    source_type: str
    source_path: str
    status: str
    visibility: str = "private"
    allowed_roles: list[str] = Field(default_factory=list)
    size_bytes: int
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class DocumentUploadOptions(BaseModel):
    visibility: str = Field(default="private", pattern="^(private|role|tenant|team|public)$")
    allowed_roles: list[str] = Field(default_factory=list, max_length=20)


class AddDocumentToBucketRequest(BaseModel):
    document_id: str = Field(..., min_length=1, max_length=36)
