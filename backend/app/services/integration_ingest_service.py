"""Inbound document ingest for n8n / external orchestrators (E4)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import KnowledgeBucket
from app.services.access_policy import UserContext
from app.services.bucket_service import BucketService


class IntegrationIngestService:
    def __init__(
        self,
        *,
        bucket_service: BucketService,
        default_bucket_name: str,
    ) -> None:
        self._bucket_service = bucket_service
        self._default_bucket_name = default_bucket_name

    async def ensure_integrations_bucket(
        self,
        *,
        user: UserContext,
        bucket_id: str | None = None,
        bucket_name: str | None = None,
    ) -> KnowledgeBucket:
        if bucket_id:
            async with self._bucket_service.session_factory() as session:
                bucket = await session.scalar(
                    select(KnowledgeBucket).where(
                        KnowledgeBucket.tenant_id == user.tenant_id,
                        KnowledgeBucket.id == bucket_id,
                    )
                )
                if bucket is None:
                    raise LookupError(f"Bucket not found: {bucket_id}")
                return bucket

        name = (bucket_name or self._default_bucket_name).strip()
        async with self._bucket_service.session_factory() as session:
            existing = await session.scalar(
                select(KnowledgeBucket).where(
                    KnowledgeBucket.tenant_id == user.tenant_id,
                    KnowledgeBucket.name == name,
                )
            )
            if existing is not None:
                return existing

        try:
            return await self._bucket_service.create_bucket(
                tenant_id=user.tenant_id,
                name=name,
                description="Documents delivered by n8n / integration workflows (E4).",
                owner_user_id=user.user_id,
            )
        except IntegrityError:
            async with self._bucket_service.session_factory() as session:
                bucket = await session.scalar(
                    select(KnowledgeBucket).where(
                        KnowledgeBucket.tenant_id == user.tenant_id,
                        KnowledgeBucket.name == name,
                    )
                )
                if bucket is None:
                    raise
                return bucket

    async def ingest_bytes(
        self,
        *,
        user: UserContext,
        file_name: str,
        content: bytes,
        content_type: str | None,
        bucket_id: str | None = None,
        bucket_name: str | None = None,
        visibility: str = "tenant",
        allowed_roles: list[str] | None = None,
        integration_source: str = "n8n",
        channel: str = "disk",
        external_ref: str | None = None,
    ) -> tuple[object, list[str], KnowledgeBucket, dict[str, object]]:
        if not content:
            raise ValueError("Uploaded file is empty.")

        bucket = await self.ensure_integrations_bucket(
            user=user,
            bucket_id=bucket_id,
            bucket_name=bucket_name,
        )
        integration_metadata: dict[str, object] = {
            "source": integration_source,
            "channel": channel,
            "integration": "e4_inbound",
        }
        if external_ref:
            integration_metadata["external_ref"] = external_ref

        upload = await self._bucket_service.stage_uploaded_document(
            user=user,
            file_name=file_name,
            content=content,
            content_type=content_type,
            extra_metadata=integration_metadata,
        )
        committed = await self._bucket_service.commit_bucket_documents(
            user=user,
            bucket_id=bucket.id,
            staged_upload_ids=[upload.id],
            existing_document_ids=[],
            removed_document_ids=[],
            visibility=visibility,
            allowed_roles=allowed_roles or [],
        )
        if committed is None:
            raise LookupError(f"Bucket not found: {bucket.id}")
        documents, indexing_job_ids = committed
        if not documents:
            raise RuntimeError("Ingest committed zero documents.")
        document = documents[0]
        metadata = dict(getattr(document, "metadata_json", {}) or {})
        metadata.update(integration_metadata)
        return document, indexing_job_ids, bucket, metadata
