import logging
import uuid
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.qdrant_store import QdrantStore
from app.db.models import BucketDocument, DocumentAsset, DocumentIndexingJob
from app.services.chunking import DocumentChunk, chunk_documents
from app.services.document_loader import RawDocument, load_raw_documents
from app.services.image_digest_service import load_image_digest_documents
from app.services.indexing_event_publisher import IndexingEventPublisher
from app.services.object_storage import (
    LocalFilesystemStorage,
    ObjectStorage,
    display_name_from_ref,
)
from app.services.ollama_client import OllamaClient

logger = logging.getLogger(__name__)
IMAGE_SOURCE_TYPES = {"png", "jpg", "jpeg"}


class DocumentIndexingService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        qdrant_store: QdrantStore,
        ollama_client: OllamaClient,
        embedding_model: str,
        image_vision_enabled: bool = False,
        image_vision_model: str | None = None,
        event_publisher: IndexingEventPublisher | None = None,
        object_storage: ObjectStorage | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._qdrant_store = qdrant_store
        self._ollama_client = ollama_client
        self._embedding_model = embedding_model
        self._image_vision_enabled = image_vision_enabled
        self._image_vision_model = image_vision_model
        self._event_publisher = event_publisher
        self._object_storage = object_storage

    async def process_jobs(self, job_ids: list[str]) -> None:
        for job_id in job_ids:
            await self.process_job(job_id)

    async def process_job(self, job_id: str) -> None:
        async with self._session_factory() as session:
            job = await session.scalar(
                select(DocumentIndexingJob).where(DocumentIndexingJob.id == job_id)
            )
            if job is None:
                return
            if job.status == "completed":
                return
            update_document_status = _should_update_document_status(job)
            document = await session.scalar(
                select(DocumentAsset).where(DocumentAsset.id == job.document_id)
            )
            if document is None:
                job.status = "failed"
                job.error = "Document asset not found."
                await session.commit()
                await self._publish_failed(
                    job_id=job_id,
                    document_id=None,
                    bucket_id=job.bucket_id,
                    tenant_id=job.tenant_id,
                    error="Document asset not found.",
                )
                return
            job.status = "running"
            job.attempts += 1
            if update_document_status:
                document.status = "indexing"
            bucket_link = await _get_bucket_link(session=session, job=job)
            if bucket_link is not None:
                bucket_link.indexing_status = "indexing"
                bucket_link.indexing_error = None
            await session.commit()
            tenant_id = job.tenant_id
            bucket_id = job.bucket_id
            document_id = document.id

        try:
            chunks_indexed = await self._index_document(document=document, bucket_id=bucket_id)
        except Exception as exc:
            async with self._session_factory() as session:
                failed_job = await session.scalar(
                    select(DocumentIndexingJob).where(DocumentIndexingJob.id == job_id)
                )
                failed_document = await session.scalar(
                    select(DocumentAsset).where(DocumentAsset.id == document.id)
                )
                if failed_job is not None:
                    failed_job.status = "failed"
                    failed_job.error = str(exc)
                if failed_job is not None and _should_update_document_status(failed_job) and failed_document is not None:
                    failed_document.status = "index_failed"
                    failed_document.error = str(exc)
                if failed_job is not None:
                    failed_link = await _get_bucket_link(session=session, job=failed_job)
                    if failed_link is not None:
                        failed_link.indexing_status = "index_failed"
                        failed_link.indexing_error = str(exc)
                await session.commit()
            await self._publish_failed(
                job_id=job_id,
                document_id=document_id,
                bucket_id=bucket_id,
                tenant_id=tenant_id,
                error=str(exc),
            )
            return

        async with self._session_factory() as session:
            completed_job = await session.scalar(
                select(DocumentIndexingJob).where(DocumentIndexingJob.id == job_id)
            )
            completed_document = await session.scalar(
                select(DocumentAsset).where(DocumentAsset.id == document.id)
            )
            if completed_job is not None:
                completed_job.status = "completed"
                completed_job.chunks_indexed = chunks_indexed
                completed_job.error = None
            if completed_job is not None and completed_document is not None:
                completed_document.status = "indexed"
                completed_document.error = None
            if completed_job is not None:
                completed_link = await _get_bucket_link(session=session, job=completed_job)
                if completed_link is not None:
                    completed_link.indexing_status = "indexed"
                    completed_link.indexing_error = None
            await session.commit()
        await self._publish_indexed(
            job_id=job_id,
            document_id=document_id,
            bucket_id=bucket_id,
            tenant_id=tenant_id,
            chunks_indexed=chunks_indexed,
        )

    async def _publish_indexed(
        self,
        *,
        job_id: str,
        document_id: str,
        bucket_id: str,
        tenant_id: str,
        chunks_indexed: int,
    ) -> None:
        if self._event_publisher is None:
            return
        try:
            await self._event_publisher.publish_document_indexed(
                job_id=job_id,
                document_id=document_id,
                bucket_id=bucket_id,
                tenant_id=tenant_id,
                chunks_indexed=chunks_indexed,
            )
        except Exception:
            logger.exception("Failed to publish document.indexed for job=%s", job_id)

    async def _publish_failed(
        self,
        *,
        job_id: str,
        document_id: str | None,
        bucket_id: str | None,
        tenant_id: str | None,
        error: str,
    ) -> None:
        if self._event_publisher is None:
            return
        try:
            await self._event_publisher.publish_document_index_failed(
                job_id=job_id,
                document_id=document_id,
                bucket_id=bucket_id,
                tenant_id=tenant_id,
                error=error,
            )
        except Exception:
            logger.exception("Failed to publish document.index_failed for job=%s", job_id)

    async def _index_document(self, *, document: DocumentAsset, bucket_id: str) -> int:
        storage = self._object_storage or LocalFilesystemStorage(Path("."))
        raw_documents = _load_raw_documents_for_asset(
            document=document,
            bucket_id=bucket_id,
            object_storage=storage,
        )
        if not raw_documents and _can_build_image_digest(
            document=document,
            enabled=self._image_vision_enabled,
            vision_model=self._image_vision_model,
        ):
            raw_documents = await _load_image_digest_documents_for_asset(
                document=document,
                bucket_id=bucket_id,
                ollama_client=self._ollama_client,
                vision_model=self._image_vision_model or "",
                object_storage=storage,
            )
        chunks = chunk_documents(raw_documents)
        if not chunks:
            raise ValueError("No chunks produced for uploaded document.")

        first_vector = await self._ollama_client.embed(self._embedding_model, chunks[0].content)
        self._qdrant_store.ensure_collection(vector_size=len(first_vector), recreate=False)

        pending: list[tuple[str, list[float], dict[str, object]]] = [
            (
                _point_id_for_chunk(document_id=document.id, bucket_id=bucket_id, chunk=chunks[0]),
                first_vector,
                _payload_for_chunk(chunk=chunks[0], document=document, bucket_id=bucket_id),
            )
        ]
        for chunk in chunks[1:]:
            vector = await self._ollama_client.embed(self._embedding_model, chunk.content)
            pending.append(
                (
                    _point_id_for_chunk(document_id=document.id, bucket_id=bucket_id, chunk=chunk),
                    vector,
                    _payload_for_chunk(chunk=chunk, document=document, bucket_id=bucket_id),
                )
            )
        self._qdrant_store.upsert_chunks(pending)
        return len(pending)


def _load_raw_documents_for_asset(
    *,
    document: DocumentAsset,
    bucket_id: str,
    object_storage: ObjectStorage,
) -> list[RawDocument]:
    source_ref = document.source_path
    file_name = display_name_from_ref(source_ref)
    with TemporaryDirectory(prefix="document-index-") as temporary_dir_name:
        temporary_dir = Path(temporary_dir_name)
        temporary_path = temporary_dir / file_name
        object_storage.materialize(source_ref, temporary_path)

        loaded_documents = load_raw_documents(
            temporary_dir,
            tenant_id=document.tenant_id,
            bucket_id=bucket_id,
        )
        matching_documents = [
            raw_document
            for raw_document in loaded_documents
            if Path(raw_document.source_path) == temporary_path
        ]
        return [
            replace(
                raw_document,
                id=f"{document.id}:{raw_document.id}",
                tenant_id=document.tenant_id,
                bucket_id=bucket_id,
                source_path=source_ref,
                metadata={
                    **raw_document.metadata,
                    "document_asset_id": document.id,
                    "document_file_name": document.file_name,
                    "document_visibility": document.visibility,
                },
            )
            for raw_document in matching_documents
        ]


async def _load_image_digest_documents_for_asset(
    *,
    document: DocumentAsset,
    bucket_id: str,
    ollama_client: OllamaClient,
    vision_model: str,
    object_storage: ObjectStorage,
) -> list[RawDocument]:
    source_ref = document.source_path
    file_name = display_name_from_ref(source_ref)
    with TemporaryDirectory(prefix="document-index-vision-") as temporary_dir_name:
        temporary_dir = Path(temporary_dir_name)
        temporary_path = temporary_dir / file_name
        object_storage.materialize(source_ref, temporary_path)

        loaded_documents = await load_image_digest_documents(
            temporary_dir,
            ollama_client=ollama_client,
            vision_model=vision_model,
            tenant_id=document.tenant_id,
            bucket_id=bucket_id,
        )
        matching_documents = [
            raw_document
            for raw_document in loaded_documents
            if Path(raw_document.source_path) == temporary_path
        ]
        return [
            replace(
                raw_document,
                id=f"{document.id}:{raw_document.id}",
                tenant_id=document.tenant_id,
                bucket_id=bucket_id,
                source_path=source_ref,
                metadata={
                    **raw_document.metadata,
                    "document_asset_id": document.id,
                    "document_file_name": document.file_name,
                    "document_visibility": document.visibility,
                },
            )
            for raw_document in matching_documents
        ]


def _can_build_image_digest(
    *,
    document: DocumentAsset,
    enabled: bool,
    vision_model: str | None,
) -> bool:
    return (
        enabled
        and bool((vision_model or "").strip())
        and document.source_type.lower() in IMAGE_SOURCE_TYPES
    )


def _should_update_document_status(job: DocumentIndexingJob) -> bool:
    source = str(job.metadata_json.get("source") or "")
    return source in {"personal_commit", "bucket_commit", "retry_indexing"}


async def _get_bucket_link(
    *,
    session: AsyncSession,
    job: DocumentIndexingJob,
) -> BucketDocument | None:
    if job.bucket_id == "__personal__":
        return None
    return await session.scalar(
        select(BucketDocument).where(
            BucketDocument.tenant_id == job.tenant_id,
            BucketDocument.bucket_id == job.bucket_id,
            BucketDocument.document_id == job.document_id,
        )
    )


def _point_id_for_chunk(*, document_id: str, bucket_id: str, chunk: DocumentChunk) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{document_id}:{bucket_id}:{chunk.id}"))


def _payload_for_chunk(
    *,
    chunk: DocumentChunk,
    document: DocumentAsset,
    bucket_id: str,
) -> dict[str, object]:
    return {
        "document_id": document.id,
        "tenant_id": document.tenant_id,
        "bucket_id": bucket_id,
        "chunk_id": chunk.id,
        "chunk_index": chunk.chunk_index,
        "domain": chunk.domain,
        "source_type": chunk.source_type,
        "source_path": chunk.source_path,
        "processing_status": "indexed",
        "title": chunk.title,
        "content": chunk.content,
        "feature": chunk.feature,
        "document_metadata": chunk.metadata,
        "language": "ru",
    }
