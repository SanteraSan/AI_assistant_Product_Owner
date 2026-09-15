from urllib.parse import unquote

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError

from app.db.models import DocumentAsset, KnowledgeBucket, StagedDocumentUpload
from app.dependencies.auth import get_current_user
from app.models.bucket import (
    BucketCreateRequest,
    BucketResponse,
    BucketUpdateRequest,
    CommitBucketDocumentsRequest,
    CommitBucketDocumentsResponse,
    CommitPersonalDocumentsRequest,
    DocumentResponse,
    DownloadBucketDocumentsRequest,
    StagedDocumentResponse,
)
from app.services.access_policy import UserContext, parse_roles
from app.services.bucket_service import BucketDownloadResult, BucketService
from app.services.document_download import (
    archive_filename,
    build_zip_bytes,
    content_disposition,
    guess_media_type,
    safe_download_name,
)
from app.services.document_indexing_service import DocumentIndexingService
from app.services.indexing_job_dispatcher import IndexingJobDispatcher


DOCUMENT_VISIBILITIES = {"private", "role", "tenant", "team", "public"}


def create_bucket_router(
    *,
    bucket_service: BucketService,
    document_indexing_service: DocumentIndexingService | None = None,
    indexing_job_dispatcher: IndexingJobDispatcher | None = None,
    default_tenant_id: str,
) -> APIRouter:
    del default_tenant_id  # tenant comes from authenticated service JWT only
    router = APIRouter(tags=["buckets"])

    async def _dispatch_indexing(
        *,
        job_ids: list[str],
        background_tasks: BackgroundTasks,
        user: UserContext,
        request: Request | None = None,
    ) -> None:
        if indexing_job_dispatcher is not None:
            await indexing_job_dispatcher.dispatch(
                job_ids=job_ids,
                background_tasks=background_tasks,
                tenant_id=user.tenant_id,
                request_id=(
                    request.headers.get("x-request-id")
                    if request is not None
                    else None
                ),
            )
            return
        if document_indexing_service is not None and job_ids:
            background_tasks.add_task(document_indexing_service.process_jobs, job_ids)

    def normalized_visibility(raw_visibility: str) -> str:
        visibility = raw_visibility.strip().lower()
        if visibility not in DOCUMENT_VISIBILITIES:
            raise HTTPException(status_code=422, detail="Unsupported document visibility.")
        return visibility

    def decoded_file_name(file_name: str, encoding: str | None) -> str:
        if (encoding or "").strip().lower() == "uri-component":
            return unquote(file_name)
        return file_name

    @router.get("/buckets", response_model=list[BucketResponse])
    async def list_buckets(
        user: UserContext = Depends(get_current_user),
    ) -> list[BucketResponse]:
        buckets = await bucket_service.list_buckets(tenant_id=user.tenant_id)
        return [
            _bucket_response(bucket=bucket, document_count=document_count)
            for bucket, document_count in buckets
        ]

    @router.post("/buckets", response_model=BucketResponse, status_code=201)
    async def create_bucket(
        payload: BucketCreateRequest,
        user: UserContext = Depends(get_current_user),
    ) -> BucketResponse:
        try:
            bucket = await bucket_service.create_bucket(
                tenant_id=user.tenant_id,
                name=payload.name,
                description=payload.description,
                owner_user_id=user.user_id,
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
        user: UserContext = Depends(get_current_user),
    ) -> BucketResponse:
        bucket = await bucket_service.update_bucket(
            tenant_id=user.tenant_id,
            bucket_id=bucket_id,
            name=payload.name,
            description=payload.description,
        )
        if bucket is None:
            raise HTTPException(status_code=404, detail="Bucket not found.")
        return _bucket_response(bucket=bucket, document_count=0)

    @router.delete("/buckets/{bucket_id}", status_code=204)
    async def delete_bucket(
        bucket_id: str,
        user: UserContext = Depends(get_current_user),
    ) -> None:
        deleted = await bucket_service.delete_bucket(
            tenant_id=user.tenant_id,
            bucket_id=bucket_id,
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="Bucket not found.")

    @router.get("/buckets/{bucket_id}/documents", response_model=list[DocumentResponse])
    async def list_documents(
        bucket_id: str,
        user: UserContext = Depends(get_current_user),
    ) -> list[DocumentResponse]:
        documents = await bucket_service.list_documents(
            user=user,
            bucket_id=bucket_id,
        )
        if documents is None:
            raise HTTPException(status_code=404, detail="Bucket not found.")
        return [
            _document_response(document, bucket_id=bucket_id, bucket_link=bucket_link)
            for document, bucket_link in documents
        ]

    @router.get("/buckets/{bucket_id}/documents/{document_id}/download")
    async def download_bucket_document(
        bucket_id: str,
        document_id: str,
        user: UserContext = Depends(get_current_user),
    ) -> Response:
        result = await bucket_service.collect_bucket_download(
            user=user,
            bucket_id=bucket_id,
            document_ids=[document_id],
        )
        return _download_http_response(result)

    @router.post("/buckets/{bucket_id}/documents/download")
    async def download_bucket_documents(
        bucket_id: str,
        payload: DownloadBucketDocumentsRequest,
        user: UserContext = Depends(get_current_user),
    ) -> Response:
        result = await bucket_service.collect_bucket_download(
            user=user,
            bucket_id=bucket_id,
            document_ids=payload.document_ids,
        )
        return _download_http_response(result)

    @router.get("/documents/my", response_model=list[DocumentResponse])
    async def list_my_documents(
        user: UserContext = Depends(get_current_user),
    ) -> list[DocumentResponse]:
        documents = await bucket_service.list_my_documents(user=user)
        return [_document_response(document) for document in documents]

    @router.get("/documents/available", response_model=list[DocumentResponse])
    async def list_available_documents(
        user: UserContext = Depends(get_current_user),
    ) -> list[DocumentResponse]:
        documents = await bucket_service.list_available_documents(user=user)
        return [_document_response(document) for document in documents]

    @router.post("/documents/stage", response_model=StagedDocumentResponse, status_code=201)
    async def stage_document_upload(
        request: Request,
        file_name: str = Header(default="uploaded-file", alias="X-File-Name"),
        file_name_encoding: str | None = Header(default=None, alias="X-File-Name-Encoding"),
        user: UserContext = Depends(get_current_user),
    ) -> StagedDocumentResponse:
        content = await request.body()
        if not content:
            raise HTTPException(status_code=422, detail="Uploaded file is empty.")
        upload = await bucket_service.stage_uploaded_document(
            user=user,
            file_name=decoded_file_name(file_name, file_name_encoding),
            content=content,
            content_type=request.headers.get("content-type"),
        )
        return _staged_document_response(upload)

    @router.delete("/documents/stage/{upload_id}", status_code=204)
    async def cancel_document_upload(
        upload_id: str,
        user: UserContext = Depends(get_current_user),
    ) -> None:
        cancelled = await bucket_service.cancel_staged_upload(
            user=user,
            upload_id=upload_id,
        )
        if not cancelled:
            raise HTTPException(status_code=404, detail="Staged upload not found.")

    @router.post(
        "/buckets/{bucket_id}/documents/upload",
        response_model=DocumentResponse,
        status_code=201,
    )
    async def upload_document(
        bucket_id: str,
        request: Request,
        file_name: str = Header(default="uploaded-file", alias="X-File-Name"),
        file_name_encoding: str | None = Header(default=None, alias="X-File-Name-Encoding"),
        visibility: str = Header(default="private", alias="X-Document-Visibility"),
        allowed_roles: str | None = Header(default=None, alias="X-Document-Roles"),
        user: UserContext = Depends(get_current_user),
    ) -> DocumentResponse:
        content = await request.body()
        if not content:
            raise HTTPException(status_code=422, detail="Uploaded file is empty.")
        document = await bucket_service.save_uploaded_document(
            user=user,
            bucket_id=bucket_id,
            file_name=decoded_file_name(file_name, file_name_encoding),
            content=content,
            content_type=request.headers.get("content-type"),
            visibility=normalized_visibility(visibility),
            allowed_roles=sorted(parse_roles(allowed_roles)),
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Bucket not found.")
        return _document_response(document, bucket_id=bucket_id)

    @router.post("/documents/upload", response_model=DocumentResponse, status_code=201)
    async def upload_personal_document(
        request: Request,
        file_name: str = Header(default="uploaded-file", alias="X-File-Name"),
        file_name_encoding: str | None = Header(default=None, alias="X-File-Name-Encoding"),
        visibility: str = Header(default="private", alias="X-Document-Visibility"),
        allowed_roles: str | None = Header(default=None, alias="X-Document-Roles"),
        user: UserContext = Depends(get_current_user),
    ) -> DocumentResponse:
        content = await request.body()
        if not content:
            raise HTTPException(status_code=422, detail="Uploaded file is empty.")
        document = await bucket_service.save_uploaded_document(
            user=user,
            bucket_id=None,
            file_name=decoded_file_name(file_name, file_name_encoding),
            content=content,
            content_type=request.headers.get("content-type"),
            visibility=normalized_visibility(visibility),
            allowed_roles=sorted(parse_roles(allowed_roles)),
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Bucket not found.")
        return _document_response(document)

    @router.post(
        "/documents/-/commit-personal",
        response_model=CommitBucketDocumentsResponse,
    )
    async def commit_personal_documents(
        payload: CommitPersonalDocumentsRequest,
        background_tasks: BackgroundTasks,
        request: Request,
        user: UserContext = Depends(get_current_user),
    ) -> CommitBucketDocumentsResponse:
        documents, indexing_job_ids = await bucket_service.commit_personal_documents(
            user=user,
            staged_upload_ids=payload.staged_upload_ids,
            visibility=payload.visibility,
            allowed_roles=payload.allowed_roles,
        )
        await _dispatch_indexing(
            job_ids=indexing_job_ids,
            background_tasks=background_tasks,
            user=user,
            request=request,
        )
        return CommitBucketDocumentsResponse(
            documents=[_document_response(document) for document in documents],
            indexing_job_ids=indexing_job_ids,
        )

    @router.post(
        "/buckets/{bucket_id}/documents/{document_id}",
        response_model=DocumentResponse,
        status_code=201,
    )
    async def add_existing_document_to_bucket(
        bucket_id: str,
        document_id: str,
        user: UserContext = Depends(get_current_user),
    ) -> DocumentResponse:
        document = await bucket_service.add_document_to_bucket(
            user=user,
            bucket_id=bucket_id,
            document_id=document_id,
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Bucket or document not found.")
        return _document_response(document, bucket_id=bucket_id)

    @router.post(
        "/buckets/{bucket_id}/documents/-/commit",
        response_model=CommitBucketDocumentsResponse,
    )
    async def commit_bucket_documents(
        bucket_id: str,
        payload: CommitBucketDocumentsRequest,
        background_tasks: BackgroundTasks,
        request: Request,
        user: UserContext = Depends(get_current_user),
    ) -> CommitBucketDocumentsResponse:
        committed = await bucket_service.commit_bucket_documents(
            user=user,
            bucket_id=bucket_id,
            staged_upload_ids=payload.staged_upload_ids,
            existing_document_ids=payload.existing_document_ids,
            removed_document_ids=payload.removed_document_ids,
            visibility=payload.visibility,
            allowed_roles=payload.allowed_roles,
        )
        if committed is None:
            raise HTTPException(status_code=404, detail="Bucket not found.")
        documents, indexing_job_ids = committed
        await _dispatch_indexing(
            job_ids=indexing_job_ids,
            background_tasks=background_tasks,
            user=user,
            request=request,
        )
        return CommitBucketDocumentsResponse(
            documents=[
                _document_response(document, bucket_id=bucket_id)
                for document in documents
            ],
            indexing_job_ids=indexing_job_ids,
        )

    @router.delete("/buckets/{bucket_id}/documents/{document_id}", status_code=204)
    async def remove_document_from_bucket(
        bucket_id: str,
        document_id: str,
        user: UserContext = Depends(get_current_user),
    ) -> None:
        removed = await bucket_service.remove_document_from_bucket(
            user=user,
            bucket_id=bucket_id,
            document_id=document_id,
        )
        if removed is None:
            raise HTTPException(status_code=404, detail="Bucket not found.")

    @router.delete("/documents/{document_id}", status_code=204)
    async def delete_document(
        document_id: str,
        user: UserContext = Depends(get_current_user),
    ) -> None:
        result = await bucket_service.delete_document(
            user=user,
            document_id=document_id,
        )
        if result.not_found:
            raise HTTPException(status_code=404, detail="Document not found.")
        if result.forbidden:
            raise HTTPException(status_code=403, detail="Document cannot be deleted by this user.")
        if result.in_use_buckets:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason": "document_in_use",
                    "buckets": [
                        {"id": bucket_id, "name": bucket_name}
                        for bucket_id, bucket_name in result.in_use_buckets
                    ],
                },
            )

    @router.post(
        "/documents/{document_id}/retry-indexing",
        response_model=CommitBucketDocumentsResponse,
    )
    async def retry_document_indexing(
        document_id: str,
        background_tasks: BackgroundTasks,
        request: Request,
        bucket_id: str | None = None,
        user: UserContext = Depends(get_current_user),
    ) -> CommitBucketDocumentsResponse:
        retried = await bucket_service.retry_document_indexing(
            user=user,
            document_id=document_id,
            bucket_id=bucket_id,
        )
        if retried is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        document, indexing_job_id = retried
        await _dispatch_indexing(
            job_ids=[indexing_job_id],
            background_tasks=background_tasks,
            user=user,
            request=request,
        )
        return CommitBucketDocumentsResponse(
            documents=[_document_response(document, bucket_id=bucket_id)],
            indexing_job_ids=[indexing_job_id],
        )

    @router.get("/documents/{document_id}/status", response_model=DocumentResponse)
    async def get_document_status(
        document_id: str,
        user: UserContext = Depends(get_current_user),
    ) -> DocumentResponse:
        document = await bucket_service.get_document(
            user=user,
            document_id=document_id,
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        return _document_response(document)

    return router


def _download_http_response(result: BucketDownloadResult) -> Response:
    if result.forbidden:
        raise HTTPException(status_code=403, detail="Document is not readable.")
    if result.not_found:
        raise HTTPException(status_code=404, detail="Document not found.")
    if result.missing_file:
        raise HTTPException(status_code=404, detail="Document file is missing.")
    if not result.files:
        raise HTTPException(status_code=404, detail="Document not found.")
    if len(result.files) == 1:
        item = result.files[0]
        file_name = safe_download_name(item.file_name)
        return Response(
            content=item.content,
            media_type=guess_media_type(file_name),
            headers={"Content-Disposition": content_disposition(file_name)},
        )
    payload = build_zip_bytes([(item.file_name, item.content) for item in result.files])
    zip_name = archive_filename(result.bucket_name)
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": content_disposition(zip_name)},
    )


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


def _document_response(
    document: DocumentAsset,
    *,
    bucket_id: str | None = None,
    bucket_link=None,
) -> DocumentResponse:
    bucket_indexing_status = getattr(bucket_link, "indexing_status", None)
    return DocumentResponse(
        id=document.id,
        tenant_id=document.tenant_id,
        bucket_id=bucket_id,
        owner_user_id=document.owner_user_id,
        title=document.title,
        file_name=document.file_name,
        source_type=document.source_type,
        source_path=document.source_path,
        status=bucket_indexing_status or document.status,
        bucket_indexing_status=bucket_indexing_status,
        visibility=document.visibility,
        allowed_roles=document.allowed_roles,
        size_bytes=document.size_bytes,
        error=document.error,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _staged_document_response(upload: StagedDocumentUpload) -> StagedDocumentResponse:
    return StagedDocumentResponse(
        id=upload.id,
        tenant_id=upload.tenant_id,
        owner_user_id=upload.owner_user_id,
        original_file_name=upload.original_file_name,
        source_type=upload.source_type,
        status=upload.status,
        size_bytes=upload.size_bytes,
        error=upload.error,
        created_at=upload.created_at,
        expires_at=upload.expires_at,
        updated_at=upload.updated_at,
    )
