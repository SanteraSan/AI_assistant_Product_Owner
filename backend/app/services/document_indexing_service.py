import uuid
from dataclasses import replace
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.qdrant_store import QdrantStore
from app.db.models import BucketDocument, DocumentAsset, DocumentIndexingJob
from app.services.chunking import DocumentChunk, chunk_documents
from app.services.document_loader import RawDocument, load_raw_documents
from app.services.image_digest_service import load_image_digest_documents
from app.services.ollama_client import OllamaClient

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
    ) -> None:
        self._session_factory = session_factory
        self._qdrant_store = qdrant_store
        self._ollama_client = ollama_client
        self._embedding_model = embedding_model
        self._image_vision_enabled = image_vision_enabled
        self._image_vision_model = image_vision_model

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
            update_document_status = _should_update_document_status(job)
            document = await session.scalar(
                select(DocumentAsset).where(DocumentAsset.id == job.document_id)
            )
            if document is None:
                job.status = "failed"
                job.error = "Document asset not found."
                await session.commit()
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

        try:
            chunks_indexed = await self._index_document(document=document, bucket_id=job.bucket_id)
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

    async def _index_document(self, *, document: DocumentAsset, bucket_id: str) -> int:
        raw_documents = _load_raw_documents_for_asset(document=document, bucket_id=bucket_id)
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


def _load_raw_documents_for_asset(*, document: DocumentAsset, bucket_id: str) -> list[RawDocument]:
    source_path = Path(document.source_path)
    with TemporaryDirectory(prefix="document-index-") as temporary_dir_name:
        temporary_dir = Path(temporary_dir_name)
        temporary_path = temporary_dir / source_path.name
        copy2(source_path, temporary_path)

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
                source_path=str(source_path),
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
) -> list[RawDocument]:
    source_path = Path(document.source_path)
    with TemporaryDirectory(prefix="document-index-vision-") as temporary_dir_name:
        temporary_dir = Path(temporary_dir_name)
        temporary_path = temporary_dir / source_path.name
        copy2(source_path, temporary_path)

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
                source_path=str(source_path),
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
