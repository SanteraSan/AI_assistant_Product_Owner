import logging
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.qdrant_store import QdrantStore
from app.db.models import (
    BucketDocument,
    DocumentAclEntry,
    DocumentAsset,
    DocumentIndexingJob,
    FeedbackItem,
)
from app.services.access_policy import UserContext, can_read_document
from app.services.chunking import DocumentChunk, chunk_documents
from app.services.document_loader import RawDocument, load_raw_documents
from app.services.feedback_index_policy import feedback_item_enters_product_qdrant
from app.services.feedback_rules import feedback_chunk_content
from app.services.image_digest_service import load_image_digest_documents
from app.services.indexing_event_publisher import IndexingEventPublisher
from app.services.object_storage import (
    LocalFilesystemStorage,
    ObjectStorage,
    display_name_from_ref,
)
from app.services.metrics import AppMetrics
from app.services.ollama_client import OllamaClient

logger = logging.getLogger(__name__)
IMAGE_SOURCE_TYPES = {"png", "jpg", "jpeg"}
_EMPTY_CHUNKS_MESSAGE = "No chunks produced for uploaded document."


class IndexingStageError(Exception):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage


@dataclass(frozen=True)
class FeedbackIndexRow:
    id: str
    feedback_class: str
    body: str
    index_in_rag: bool
    index_text: str | None = None
    scenario_id: str | None = None


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
        metrics: AppMetrics | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._qdrant_store = qdrant_store
        self._ollama_client = ollama_client
        self._embedding_model = embedding_model
        self._image_vision_enabled = image_vision_enabled
        self._image_vision_model = image_vision_model
        self._event_publisher = event_publisher
        self._object_storage = object_storage
        self._metrics = metrics

    async def process_jobs(self, job_ids: list[str], *, message_tenant_id: str | None) -> None:
        for job_id in job_ids:
            await self.process_job(job_id, message_tenant_id=message_tenant_id)

    async def process_job(self, job_id: str, *, message_tenant_id: str | None) -> None:
        async with self._session_factory() as session:
            job = await session.scalar(
                select(DocumentIndexingJob).where(DocumentIndexingJob.id == job_id)
            )
            if job is None:
                return
            if not _message_tenant_matches(message_tenant_id, job.tenant_id):
                logger.warning(
                    "Indexing skipped job_id=%s document_id=%s stage=%s",
                    job.id,
                    job.document_id,
                    "tenant_check",
                )
                return
            if job.status == "completed":
                return
            document = await session.scalar(
                select(DocumentAsset).where(
                    DocumentAsset.id == job.document_id,
                    DocumentAsset.tenant_id == job.tenant_id,
                )
            )
            if document is None:
                await self._fail_before_running(
                    session=session,
                    job=job,
                    document=None,
                    stage="load_asset",
                    error="Document asset not found.",
                    update_documents=False,
                    publish=True,
                )
                return
            acl_error = await _acl_check_error(session=session, job=job, document=document)
            if acl_error is not None:
                await self._fail_before_running(
                    session=session,
                    job=job,
                    document=document,
                    stage="acl_check",
                    error=acl_error,
                    update_documents=True,
                    publish=False,
                )
                return

            update_document_status = _should_update_document_status(job)
            job.status = "running"
            job.attempts += 1
            if update_document_status:
                document.status = "indexing"
            bucket_link = await _get_bucket_link(session=session, job=job)
            if bucket_link is not None:
                bucket_link.indexing_status = "indexing"
                bucket_link.indexing_error = None
            feedback_rows = await _load_feedback_index_rows(session=session, job=job)
            tenant_id = job.tenant_id
            bucket_id = job.bucket_id
            document_id = document.id
            await session.commit()

        try:
            if feedback_rows:
                chunks_indexed = await self._index_feedback_rows(
                    document=document,
                    bucket_id=bucket_id,
                    tenant_id=tenant_id,
                    rows=feedback_rows,
                )
            else:
                chunks_indexed = await self._index_document(
                    document=document,
                    bucket_id=bucket_id,
                )
        except Exception as exc:
            stage, message = _stage_and_message(exc)
            logger.error(
                "Indexing failed job_id=%s document_id=%s stage=%s",
                job_id,
                document_id,
                stage,
            )
            async with self._session_factory() as session:
                failed_job = await session.scalar(
                    select(DocumentIndexingJob).where(DocumentIndexingJob.id == job_id)
                )
                failed_document = await session.scalar(
                    select(DocumentAsset).where(DocumentAsset.id == document.id)
                )
                if failed_job is not None:
                    failed_job.status = "failed"
                    failed_job.error = message
                    failed_job.failed_stage = stage
                    await _apply_index_failed_statuses(
                        session=session,
                        job=failed_job,
                        document=failed_document,
                        error=message,
                    )
                await session.commit()
            await self._publish_failed(
                job_id=job_id,
                document_id=document_id,
                bucket_id=bucket_id,
                tenant_id=tenant_id,
                error=message,
                failed_stage=stage,
            )
            self._observe_indexing("failed")
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
                completed_job.failed_stage = None
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
        self._observe_indexing("completed")

    async def _fail_before_running(
        self,
        *,
        session: AsyncSession,
        job: DocumentIndexingJob,
        document: DocumentAsset | None,
        stage: str,
        error: str,
        update_documents: bool,
        publish: bool,
    ) -> None:
        job.attempts += 1
        job.status = "failed"
        job.failed_stage = stage
        job.error = error
        if update_documents:
            await _apply_index_failed_statuses(
                session=session,
                job=job,
                document=document,
                error=error,
            )
        document_id = job.document_id
        bucket_id = job.bucket_id
        tenant_id = job.tenant_id
        job_id = job.id
        await session.commit()
        logger.error(
            "Indexing failed job_id=%s document_id=%s stage=%s",
            job_id,
            document_id,
            stage,
        )
        if publish:
            await self._publish_failed(
                job_id=job_id,
                document_id=document_id,
                bucket_id=bucket_id,
                tenant_id=tenant_id,
                error=error,
                failed_stage=stage,
            )
        self._observe_indexing("failed")

    def _observe_indexing(self, result: str) -> None:
        if self._metrics is not None:
            self._metrics.observe_indexing(result=result)

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
        failed_stage: str,
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
                failed_stage=failed_stage,
            )
        except Exception:
            logger.exception("Failed to publish document.index_failed for job=%s", job_id)

    async def _index_document(self, *, document: DocumentAsset, bucket_id: str) -> int:
        storage = self._object_storage or LocalFilesystemStorage(Path("."))
        raw_documents = await load_asset_raw_documents(
            document=document,
            bucket_id=bucket_id,
            object_storage=storage,
            ollama_client=self._ollama_client,
            image_vision_enabled=self._image_vision_enabled,
            image_vision_model=self._image_vision_model,
        )
        chunks = chunk_documents(raw_documents)
        if not chunks:
            raise ValueError(_EMPTY_CHUNKS_MESSAGE)
        return await self._embed_and_upsert(chunks=chunks, document=document, bucket_id=bucket_id)

    async def _index_feedback_rows(
        self,
        *,
        document: DocumentAsset,
        bucket_id: str,
        tenant_id: str,
        rows: list[FeedbackIndexRow],
    ) -> int:
        chunks = _feedback_chunks(
            document=document,
            bucket_id=bucket_id,
            tenant_id=tenant_id,
            rows=rows,
        )
        if not chunks:
            return 0
        return await self._embed_and_upsert(
            chunks=chunks,
            document=document,
            bucket_id=bucket_id,
            tenant_id=tenant_id,
            feedback=True,
        )

    async def _embed_and_upsert(
        self,
        *,
        chunks: list[DocumentChunk],
        document: DocumentAsset,
        bucket_id: str,
        tenant_id: str | None = None,
        feedback: bool = False,
    ) -> int:
        first_vector = await self._embed_for_index(chunks[0].content)
        self._qdrant_store.ensure_collection(vector_size=len(first_vector), recreate=False)
        pending: list[tuple[str, list[float], dict[str, object]]] = [
            (
                _point_id_for_chunk(document_id=document.id, bucket_id=bucket_id, chunk=chunks[0]),
                first_vector,
                _chunk_payload(
                    chunk=chunks[0],
                    document=document,
                    bucket_id=bucket_id,
                    tenant_id=tenant_id,
                    feedback=feedback,
                ),
            )
        ]
        for chunk in chunks[1:]:
            vector = await self._embed_for_index(chunk.content)
            pending.append(
                (
                    _point_id_for_chunk(document_id=document.id, bucket_id=bucket_id, chunk=chunk),
                    vector,
                    _chunk_payload(
                        chunk=chunk,
                        document=document,
                        bucket_id=bucket_id,
                        tenant_id=tenant_id,
                        feedback=feedback,
                    ),
                )
            )
        self._upsert_for_index(pending)
        return len(pending)

    async def _embed_for_index(self, content: str) -> list[float]:
        try:
            return await self._ollama_client.embed(self._embedding_model, content)
        except IndexingStageError:
            raise
        except Exception as exc:
            raise IndexingStageError("embed", str(exc)) from exc

    def _upsert_for_index(
        self,
        pending: list[tuple[str, list[float], dict[str, object]]],
    ) -> None:
        try:
            self._qdrant_store.upsert_chunks(pending)
        except IndexingStageError:
            raise
        except Exception as exc:
            raise IndexingStageError("upsert", str(exc)) from exc


def combine_raw_documents(
    primary: list[RawDocument],
    extra: list[RawDocument],
) -> list[RawDocument]:
    merged = list(primary)
    seen = {document.id for document in merged}
    for document in extra:
        if document.id in seen:
            continue
        merged.append(document)
        seen.add(document.id)
    return merged


async def load_asset_raw_documents(
    *,
    document: DocumentAsset,
    bucket_id: str,
    object_storage: ObjectStorage,
    ollama_client: OllamaClient,
    image_vision_enabled: bool,
    image_vision_model: str | None,
) -> list[RawDocument]:
    """OCR/text first. Image files also keep a vision digest beside non-empty OCR.

    Office files stay on their parsed text here. Embedded-image digest for
    DOCX/XLSX upload is a separate gap and is not filled by this path.
    """
    raw_documents = _load_raw_documents_for_asset(
        document=document,
        bucket_id=bucket_id,
        object_storage=object_storage,
    )
    if _can_build_image_digest(
        document=document,
        enabled=image_vision_enabled,
        vision_model=image_vision_model,
    ):
        digest_documents = await _load_image_digest_documents_for_asset(
            document=document,
            bucket_id=bucket_id,
            ollama_client=ollama_client,
            vision_model=image_vision_model or "",
            object_storage=object_storage,
        )
        raw_documents = combine_raw_documents(raw_documents, digest_documents)
    return raw_documents


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
        _materialize_for_index(object_storage, source_ref, temporary_path)

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
        _materialize_for_index(object_storage, source_ref, temporary_path)

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
        "synthetic": chunk.metadata.get("synthetic") is True,
        "language": "ru",
    }


def _chunk_payload(
    *,
    chunk: DocumentChunk,
    document: DocumentAsset,
    bucket_id: str,
    tenant_id: str | None,
    feedback: bool,
) -> dict[str, object]:
    payload = _payload_for_chunk(chunk=chunk, document=document, bucket_id=bucket_id)
    if not feedback:
        return payload
    payload["document_id"] = document.id
    payload["tenant_id"] = tenant_id if tenant_id is not None else document.tenant_id
    payload["bucket_id"] = bucket_id
    payload["feedback_item_id"] = chunk.metadata["feedback_item_id"]
    payload["feedback_class"] = chunk.metadata["feedback_class"]
    payload["index_in_rag"] = True
    return payload


def _feedback_chunks(
    *,
    document: DocumentAsset,
    bucket_id: str,
    tenant_id: str,
    rows: list[FeedbackIndexRow],
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    for row in rows:
        if not feedback_item_enters_product_qdrant(
            feedback_class=row.feedback_class,
            index_in_rag=row.index_in_rag,
        ):
            continue
        content = feedback_chunk_content(body=row.body, index_text=row.index_text)
        if not content.strip():
            continue
        metadata: dict[str, object] = {
            "feedback_item_id": row.id,
            "feedback_class": row.feedback_class,
            "document_asset_id": document.id,
        }
        if row.scenario_id is not None:
            metadata["scenario_id"] = row.scenario_id
        chunks.append(
            DocumentChunk(
                id=row.id,
                document_id=document.id,
                title=document.title,
                content=content,
                source_type="feedback",
                source_path=f"feedback:{row.id}",
                domain="feedback",
                feature=[],
                chunk_index=len(chunks),
                tenant_id=tenant_id,
                bucket_id=bucket_id,
                processing_status="indexed",
                metadata=metadata,
            )
        )
    return chunks


def _materialize_for_index(
    object_storage: ObjectStorage,
    source_ref: str,
    destination: Path,
) -> None:
    try:
        object_storage.materialize(source_ref, destination)
    except IndexingStageError:
        raise
    except Exception as exc:
        raise IndexingStageError("load_object", str(exc)) from exc


def _message_tenant_matches(message_tenant_id: str | None, job_tenant_id: str) -> bool:
    if message_tenant_id is None:
        return False
    tenant_id = message_tenant_id.strip()
    if not tenant_id:
        return False
    return tenant_id == job_tenant_id


def _roles_from_owner_json(raw: object) -> frozenset[str]:
    if not isinstance(raw, list):
        return frozenset()
    roles: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        role = item.strip()
        if role:
            roles.append(role)
    return frozenset(roles)


def _stage_and_message(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, IndexingStageError):
        return exc.stage, str(exc)
    if isinstance(exc, ValueError):
        return "parse", str(exc)
    return "index", str(exc)


async def _acl_check_error(
    *,
    session: AsyncSession,
    job: DocumentIndexingJob,
    document: DocumentAsset,
) -> str | None:
    owner_user_id = (job.owner_user_id or "").strip()
    if not owner_user_id:
        return "Indexing job has no owner."
    actor = UserContext(
        tenant_id=job.tenant_id,
        user_id=owner_user_id,
        roles=_roles_from_owner_json(job.owner_roles_json),
    )
    acl_entries = (
        await session.scalars(
            select(DocumentAclEntry).where(
                DocumentAclEntry.document_id == document.id,
                DocumentAclEntry.tenant_id == job.tenant_id,
            )
        )
    ).all()
    if not can_read_document(document=document, user=actor, acl_entries=list(acl_entries)):
        return "Document access denied."
    return None


async def _apply_index_failed_statuses(
    *,
    session: AsyncSession,
    job: DocumentIndexingJob,
    document: DocumentAsset | None,
    error: str,
) -> None:
    if document is not None and _should_update_document_status(job):
        document.status = "index_failed"
        document.error = error
    link = await _get_bucket_link(session=session, job=job)
    if link is not None:
        link.indexing_status = "index_failed"
        link.indexing_error = error


async def _load_feedback_index_rows(
    *,
    session: AsyncSession,
    job: DocumentIndexingJob,
) -> list[FeedbackIndexRow]:
    rows = (
        await session.scalars(
            select(FeedbackItem)
            .where(
                FeedbackItem.tenant_id == job.tenant_id,
                FeedbackItem.document_id == job.document_id,
            )
            .order_by(FeedbackItem.created_at, FeedbackItem.id)
        )
    ).all()
    return [
        FeedbackIndexRow(
            id=row.id,
            feedback_class=row.feedback_class,
            body=row.body,
            index_in_rag=row.index_in_rag,
            index_text=row.index_text,
            scenario_id=row.scenario_id,
        )
        for row in rows
    ]
