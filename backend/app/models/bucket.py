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
    bucket_indexing_status: str | None = None
    visibility: str = "private"
    allowed_roles: list[str] = Field(default_factory=list)
    size_bytes: int
    error: str | None = None
    created_at: datetime
    expires_at: datetime | None = None
    updated_at: datetime


class StagedDocumentResponse(BaseModel):
    id: str
    tenant_id: str
    owner_user_id: str | None = None
    original_file_name: str
    source_type: str
    status: str
    size_bytes: int
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class DocumentUploadOptions(BaseModel):
    visibility: str = Field(default="private", pattern="^(private|role|tenant|team|public)$")
    allowed_roles: list[str] = Field(default_factory=list, max_length=20)


class AddDocumentToBucketRequest(BaseModel):
    document_id: str = Field(..., min_length=1, max_length=36)


class CommitBucketDocumentsRequest(BaseModel):
    staged_upload_ids: list[str] = Field(default_factory=list, max_length=50)
    existing_document_ids: list[str] = Field(default_factory=list, max_length=50)
    removed_document_ids: list[str] = Field(default_factory=list, max_length=50)
    visibility: str = Field(default="private", pattern="^(private|role|tenant|team|public)$")
    allowed_roles: list[str] = Field(default_factory=list, max_length=20)


class CommitBucketDocumentsResponse(BaseModel):
    documents: list[DocumentResponse]
    indexing_job_ids: list[str] = Field(default_factory=list)


class CommitPersonalDocumentsRequest(BaseModel):
    staged_upload_ids: list[str] = Field(default_factory=list, max_length=50)
    visibility: str = Field(default="private", pattern="^(private|role|tenant|team|public)$")
    allowed_roles: list[str] = Field(default_factory=list, max_length=20)
