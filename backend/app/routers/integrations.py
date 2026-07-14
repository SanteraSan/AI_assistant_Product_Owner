from urllib.parse import unquote

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request

from app.dependencies.auth import get_current_user
from app.models.integrations import ExternalDbSyncResponse, IntegrationIngestResponse
from app.services.access_policy import UserContext
from app.services.document_indexing_service import DocumentIndexingService
from app.services.external_db_sync_service import ExternalDbSyncService
from app.services.indexing_job_dispatcher import IndexingJobDispatcher
from app.services.integration_ingest_service import IntegrationIngestService


DOCUMENT_VISIBILITIES = {"private", "role", "tenant", "team", "public"}


def create_integrations_router(
    *,
    integration_ingest_service: IntegrationIngestService,
    external_db_sync_service: ExternalDbSyncService,
    document_indexing_service: DocumentIndexingService | None = None,
    indexing_job_dispatcher: IndexingJobDispatcher | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/integrations", tags=["integrations"])

    def decoded_file_name(file_name: str, encoding: str | None) -> str:
        if (encoding or "").strip().lower() == "uri-component":
            return unquote(file_name)
        return file_name

    @router.post("/ingest", response_model=IntegrationIngestResponse, status_code=201)
    async def ingest_document(
        request: Request,
        background_tasks: BackgroundTasks,
        file_name: str = Header(default="uploaded-file", alias="X-File-Name"),
        file_name_encoding: str | None = Header(default=None, alias="X-File-Name-Encoding"),
        bucket_id: str | None = Header(default=None, alias="X-Bucket-Id"),
        bucket_name: str | None = Header(default=None, alias="X-Bucket-Name"),
        visibility: str = Header(default="tenant", alias="X-Document-Visibility"),
        allowed_roles: str | None = Header(default=None, alias="X-Document-Roles"),
        channel: str = Header(default="disk", alias="X-Integration-Channel"),
        external_ref: str | None = Header(default=None, alias="X-External-Ref"),
        user: UserContext = Depends(get_current_user),
    ) -> IntegrationIngestResponse:
        normalized_visibility = visibility.strip().lower()
        if normalized_visibility not in DOCUMENT_VISIBILITIES:
            raise HTTPException(status_code=422, detail="Unsupported document visibility.")
        content = await request.body()
        roles = [
            part.strip()
            for part in (allowed_roles or "").split(",")
            if part.strip()
        ]
        try:
            document, indexing_job_ids, bucket, metadata = await integration_ingest_service.ingest_bytes(
                user=user,
                file_name=decoded_file_name(file_name, file_name_encoding),
                content=content,
                content_type=request.headers.get("content-type"),
                bucket_id=bucket_id,
                bucket_name=bucket_name,
                visibility=normalized_visibility,
                allowed_roles=roles,
                integration_source="n8n",
                channel=channel.strip() or "disk",
                external_ref=external_ref,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        if indexing_job_dispatcher is not None:
            await indexing_job_dispatcher.dispatch(
                job_ids=indexing_job_ids,
                background_tasks=background_tasks,
                tenant_id=user.tenant_id,
                request_id=request.headers.get("x-request-id"),
            )
        elif document_indexing_service is not None and indexing_job_ids:
            background_tasks.add_task(document_indexing_service.process_jobs, indexing_job_ids)

        return IntegrationIngestResponse(
            document_id=document.id,
            bucket_id=bucket.id,
            file_name=document.file_name,
            status=document.status,
            indexing_job_ids=indexing_job_ids,
            metadata=metadata,
            created_at=document.created_at,
        )

    @router.post("/sync-external-db", response_model=ExternalDbSyncResponse)
    async def sync_external_db(
        user: UserContext = Depends(get_current_user),
    ) -> ExternalDbSyncResponse:
        if not user.is_admin and "analyst" not in user.roles:
            raise HTTPException(
                status_code=403,
                detail="External DB sync requires admin or analyst role.",
            )
        try:
            result = await external_db_sync_service.sync_tenant(tenant_id=user.tenant_id)
        except Exception as exc:  # noqa: BLE001 — surface sync errors to caller
            raise HTTPException(
                status_code=502,
                detail=f"External DB sync failed: {exc}",
            ) from exc
        return ExternalDbSyncResponse(
            tenant_id=str(result["tenant_id"]),
            customers_upserted=int(result["customers_upserted"]),
            tickets_upserted=int(result["tickets_upserted"]),
            status=str(result["status"]),
            synced_at=result["synced_at"],
        )

    return router
