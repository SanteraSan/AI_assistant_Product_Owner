from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy.exc import IntegrityError

from app.db.models import DocumentRecord, KnowledgeBucket
from app.models.bucket import (
    BucketCreateRequest,
    BucketResponse,
    BucketUpdateRequest,
    DocumentResponse,
)
from app.services.bucket_service import BucketService


def create_bucket_router(
    *,
    bucket_service: BucketService,
    default_tenant_id: str,
) -> APIRouter:
    router = APIRouter(tags=["buckets"])

    def tenant_from_header(x_tenant_id: str | None) -> str:
        return (x_tenant_id or default_tenant_id).strip() or default_tenant_id

    def user_from_header(x_user_id: str | None) -> str | None:
        normalized = (x_user_id or "").strip()
        return normalized or None

    @router.get("/buckets", response_model=list[BucketResponse])
    async def list_buckets(
        tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    ) -> list[BucketResponse]:
        normalized_tenant_id = tenant_from_header(tenant_id)
        buckets = await bucket_service.list_buckets(tenant_id=normalized_tenant_id)
        return [
            _bucket_response(bucket=bucket, document_count=document_count)
            for bucket, document_count in buckets
        ]

    @router.post("/buckets", response_model=BucketResponse, status_code=201)
    async def create_bucket(
        payload: BucketCreateRequest,
        tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
        user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> BucketResponse:
        try:
            bucket = await bucket_service.create_bucket(
                tenant_id=tenant_from_header(tenant_id),
                name=payload.name,
                description=payload.description,
                owner_user_id=user_from_header(user_id),
            )
        except IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail="Bucket with this name already exists for tenant.",
            ) from exc
        return _bucket_response(bucket=bucket, document_count=0)

    @router.patch("/buckets/{bucket_id}", response_model=BucketResponse)
    async def update_bucket(
        bucket_id: str,
        payload: BucketUpdateRequest,
        tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    ) -> BucketResponse:
        bucket = await bucket_service.update_bucket(
            tenant_id=tenant_from_header(tenant_id),
            bucket_id=bucket_id,
            name=payload.name,
            description=payload.description,
        )
        if bucket is None:
            raise HTTPException(status_code=404, detail="Bucket not found.")
        return _bucket_response(bucket=bucket, document_count=0)

    @router.get("/buckets/{bucket_id}/documents", response_model=list[DocumentResponse])
    async def list_documents(
        bucket_id: str,
        tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    ) -> list[DocumentResponse]:
        documents = await bucket_service.list_documents(
            tenant_id=tenant_from_header(tenant_id),
            bucket_id=bucket_id,
        )
        if documents is None:
            raise HTTPException(status_code=404, detail="Bucket not found.")
        return [_document_response(document) for document in documents]

    @router.post(
        "/buckets/{bucket_id}/documents/upload",
        response_model=DocumentResponse,
        status_code=201,
    )
    async def upload_document(
        bucket_id: str,
        request: Request,
        file_name: str = Header(default="uploaded-file", alias="X-File-Name"),
        tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    ) -> DocumentResponse:
        content = await request.body()
        if not content:
            raise HTTPException(status_code=422, detail="Uploaded file is empty.")
        document = await bucket_service.save_uploaded_document(
            tenant_id=tenant_from_header(tenant_id),
            bucket_id=bucket_id,
            file_name=file_name,
            content=content,
            content_type=request.headers.get("content-type"),
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Bucket not found.")
        return _document_response(document)

    @router.get("/documents/{document_id}/status", response_model=DocumentResponse)
    async def get_document_status(
        document_id: str,
        tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    ) -> DocumentResponse:
        document = await bucket_service.get_document(
            tenant_id=tenant_from_header(tenant_id),
            document_id=document_id,
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        return _document_response(document)

    return router


def _bucket_response(*, bucket: KnowledgeBucket, document_count: int) -> BucketResponse:
    return BucketResponse(
        id=bucket.id,
        tenant_id=bucket.tenant_id,
        name=bucket.name,
        description=bucket.description,
        status=bucket.status,
        document_count=document_count,
        created_at=bucket.created_at,
        updated_at=bucket.updated_at,
    )


def _document_response(document: DocumentRecord) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        tenant_id=document.tenant_id,
        bucket_id=document.bucket_id,
        file_name=document.file_name,
        source_type=document.source_type,
        source_path=document.source_path,
        status=document.status,
        size_bytes=document.size_bytes,
        error=document.error,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )
