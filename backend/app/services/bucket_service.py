from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    BucketDocument,
    DocumentAsset,
    DocumentIndexingJob,
    KnowledgeBucket,
    StagedDocumentUpload,
)
from app.services.access_policy import UserContext, can_manage_document, can_read_document
from app.services.object_storage import LocalFilesystemStorage, ObjectStorage, resolve_upload_root


PERSONAL_INDEX_BUCKET_ID = "__personal__"


@dataclass(frozen=True)
class DocumentDeleteResult:
    deleted: bool
    not_found: bool = False
    forbidden: bool = False
    in_use_buckets: list[tuple[str, str]] = field(default_factory=list)


class BucketService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        raw_data_dir: str,
        object_storage: ObjectStorage | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._upload_root = resolve_upload_root(raw_data_dir)
        self._storage: ObjectStorage = object_storage or LocalFilesystemStorage(self._upload_root)

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    @property
    def object_storage(self) -> ObjectStorage:
        return self._storage

    def _object_key(self, *parts: str) -> str:
        return "/".join(part.strip("/") for part in parts if part)

    async def list_buckets(self, *, tenant_id: str) -> list[tuple[KnowledgeBucket, int]]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(KnowledgeBucket, func.count(BucketDocument.id))
                .outerjoin(BucketDocument, BucketDocument.bucket_id == KnowledgeBucket.id)
                .where(KnowledgeBucket.tenant_id == tenant_id)
                .group_by(KnowledgeBucket.id)
                .order_by(KnowledgeBucket.created_at.desc())
            )
            return [(bucket, int(document_count)) for bucket, document_count in result.all()]

    async def create_bucket(
        self,
        *,
        tenant_id: str,
        name: str,
        description: str,
        owner_user_id: str | None,
    ) -> KnowledgeBucket:
        async with self._session_factory() as session:
            bucket = KnowledgeBucket(
                tenant_id=tenant_id,
                name=name.strip(),
                description=description.strip(),
                owner_user_id=owner_user_id,
                status="ready",
            )
            session.add(bucket)
            await session.commit()
            await session.refresh(bucket)
            return bucket

    async def update_bucket(
        self,
        *,
        tenant_id: str,
        bucket_id: str,
        name: str | None,
        description: str | None,
    ) -> KnowledgeBucket | None:
        async with self._session_factory() as session:
            bucket = await self._get_bucket(
                session=session,
                tenant_id=tenant_id,
                bucket_id=bucket_id,
            )
            if bucket is None:
                return None
            if name is not None:
                bucket.name = name.strip()
            if description is not None:
                bucket.description = description.strip()
            await session.commit()
            await session.refresh(bucket)
            return bucket

    async def list_documents(
        self,
        *,
        user: UserContext,
        bucket_id: str,
    ) -> list[tuple[DocumentAsset, BucketDocument]] | None:
        async with self._session_factory() as session:
            bucket = await self._get_bucket(
                session=session,
                tenant_id=user.tenant_id,
                bucket_id=bucket_id,
            )
            if bucket is None:
                return None
            result = await session.execute(
                select(DocumentAsset, BucketDocument)
                .join(BucketDocument, BucketDocument.document_id == DocumentAsset.id)
                .options(selectinload(DocumentAsset.acl_entries))
                .where(
                    BucketDocument.tenant_id == user.tenant_id,
                    BucketDocument.bucket_id == bucket_id,
                    DocumentAsset.tenant_id == user.tenant_id,
                )
                .order_by(BucketDocument.created_at.desc())
            )
            rows = list(result.all())
            return [
                (document, bucket_document)
                for document, bucket_document in rows
                if can_read_document(
                    document=document,
                    user=user,
                    acl_entries=document.acl_entries,
                )
            ]

    async def get_document(
        self,
        *,
        user: UserContext,
        document_id: str,
    ) -> DocumentAsset | None:
        async with self._session_factory() as session:
            document = await session.scalar(
                select(DocumentAsset)
                .options(selectinload(DocumentAsset.acl_entries))
                .where(
                    DocumentAsset.tenant_id == user.tenant_id,
                    DocumentAsset.id == document_id,
                )
            )
            if document is None:
                return None
            if not can_read_document(document=document, user=user, acl_entries=document.acl_entries):
                return None
            return document

    async def list_my_documents(self, *, user: UserContext) -> list[DocumentAsset]:
        async with self._session_factory() as session:
            if user.user_id is None:
                return []
            result = await session.execute(
                select(DocumentAsset)
                .where(
                    DocumentAsset.tenant_id == user.tenant_id,
                    DocumentAsset.owner_user_id == user.user_id,
                )
                .order_by(DocumentAsset.created_at.desc())
            )
            return list(result.scalars())

    async def list_available_documents(self, *, user: UserContext) -> list[DocumentAsset]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(DocumentAsset)
                .options(
                    selectinload(DocumentAsset.acl_entries),
                    selectinload(DocumentAsset.bucket_links),
                )
                .where(DocumentAsset.tenant_id == user.tenant_id)
                .order_by(DocumentAsset.created_at.desc())
            )
            documents = list(result.scalars())
            readable_documents = [
                document
                for document in documents
                if can_read_document(
                    document=document,
                    user=user,
                    acl_entries=document.acl_entries,
                )
            ]
            return _deduplicate_available_documents(readable_documents)

    async def add_document_to_bucket(
        self,
        *,
        user: UserContext,
        bucket_id: str,
        document_id: str,
    ) -> DocumentAsset | None:
        async with self._session_factory() as session:
            bucket = await self._get_bucket(
                session=session,
                tenant_id=user.tenant_id,
                bucket_id=bucket_id,
            )
            if bucket is None:
                return None
            document = await session.scalar(
                select(DocumentAsset)
                .options(selectinload(DocumentAsset.acl_entries))
                .where(
                    DocumentAsset.tenant_id == user.tenant_id,
                    DocumentAsset.id == document_id,
                )
            )
            if document is None:
                return None
            if not can_read_document(document=document, user=user, acl_entries=document.acl_entries):
                return None

            existing_link = await session.scalar(
                select(BucketDocument).where(
                    BucketDocument.tenant_id == user.tenant_id,
                    BucketDocument.bucket_id == bucket_id,
                    BucketDocument.document_id == document_id,
                )
            )
            if existing_link is None:
                session.add(
                    BucketDocument(
                        tenant_id=user.tenant_id,
                        bucket_id=bucket_id,
                        document_id=document_id,
                        added_by_user_id=user.user_id,
                    )
                )
                await session.commit()
            await session.refresh(document)
            return document

    async def remove_document_from_bucket(
        self,
        *,
        user: UserContext,
        bucket_id: str,
        document_id: str,
    ) -> bool | None:
        async with self._session_factory() as session:
            bucket = await self._get_bucket(
                session=session,
                tenant_id=user.tenant_id,
                bucket_id=bucket_id,
            )
            if bucket is None:
                return None
            link = await session.scalar(
                select(BucketDocument).where(
                    BucketDocument.tenant_id == user.tenant_id,
                    BucketDocument.bucket_id == bucket_id,
                    BucketDocument.document_id == document_id,
                )
            )
            if link is None:
                return False
            await session.delete(link)
            await session.commit()
            return True

    async def delete_document(
        self,
        *,
        user: UserContext,
        document_id: str,
    ) -> DocumentDeleteResult:
        async with self._session_factory() as session:
            document = await session.scalar(
                select(DocumentAsset)
                .options(
                    selectinload(DocumentAsset.acl_entries),
                    selectinload(DocumentAsset.bucket_links),
                )
                .where(
                    DocumentAsset.tenant_id == user.tenant_id,
                    DocumentAsset.id == document_id,
                )
            )
            if document is None:
                return DocumentDeleteResult(deleted=False, not_found=True)
            if not can_manage_document(
                document=document,
                user=user,
                acl_entries=document.acl_entries,
            ):
                return DocumentDeleteResult(deleted=False, forbidden=True)
            if not user.is_admin and (
                document.visibility != "private"
                or not user.user_id
                or document.owner_user_id != user.user_id
            ):
                return DocumentDeleteResult(deleted=False, forbidden=True)

            bucket_links = list(document.bucket_links)
            if bucket_links:
                bucket_ids = [link.bucket_id for link in bucket_links]
                buckets = (
                    await session.execute(
                        select(KnowledgeBucket).where(
                            KnowledgeBucket.tenant_id == user.tenant_id,
                            KnowledgeBucket.id.in_(bucket_ids),
                        )
                    )
                ).scalars().all()
                bucket_names = {bucket.id: bucket.name for bucket in buckets}
                return DocumentDeleteResult(
                    deleted=False,
                    in_use_buckets=[
                        (bucket_id, bucket_names.get(bucket_id, bucket_id))
                        for bucket_id in bucket_ids
                    ],
                )

            source_ref = document.source_path
            await session.delete(document)
            await session.commit()
            self._storage.delete(source_ref)
            return DocumentDeleteResult(deleted=True)

    async def delete_bucket(
        self,
        *,
        tenant_id: str,
        bucket_id: str,
    ) -> bool:
        async with self._session_factory() as session:
            bucket = await self._get_bucket(
                session=session,
                tenant_id=tenant_id,
                bucket_id=bucket_id,
            )
            if bucket is None:
                return False
            # BucketDocument links cascade-delete; DocumentAsset rows stay available.
            await session.delete(bucket)
            await session.commit()
            return True

    async def retry_document_indexing(
        self,
        *,
        user: UserContext,
        document_id: str,
        bucket_id: str | None = None,
    ) -> tuple[DocumentAsset, str] | None:
        async with self._session_factory() as session:
            document = await session.scalar(
                select(DocumentAsset)
                .options(selectinload(DocumentAsset.acl_entries))
                .where(
                    DocumentAsset.tenant_id == user.tenant_id,
                    DocumentAsset.id == document_id,
                )
            )
            if document is None:
                return None
            if not can_manage_document(
                document=document,
                user=user,
                acl_entries=document.acl_entries,
            ):
                return None

            target_bucket_id = bucket_id or PERSONAL_INDEX_BUCKET_ID
            if bucket_id is not None:
                bucket = await self._get_bucket(
                    session=session,
                    tenant_id=user.tenant_id,
                    bucket_id=bucket_id,
                )
                if bucket is None:
                    return None
                await self._ensure_bucket_document_link(
                    session=session,
                    user=user,
                    bucket_id=bucket_id,
                    document_id=document_id,
                    indexing_status="indexing",
                )

            document.status = "indexing"
            document.error = None
            job_id = str(uuid4())
            session.add(
                DocumentIndexingJob(
                    id=job_id,
                    tenant_id=user.tenant_id,
                    bucket_id=target_bucket_id,
                    document_id=document_id,
                    status="pending",
                    metadata_json={"source": "retry_indexing"},
                )
            )
            await session.commit()
            await session.refresh(document)
            return document, job_id

    async def stage_uploaded_document(
        self,
        *,
        user: UserContext,
        file_name: str,
        content: bytes,
        content_type: str | None,
        extra_metadata: dict[str, object] | None = None,
    ) -> StagedDocumentUpload:
        async with self._session_factory() as session:
            upload_id = str(uuid4())
            safe_file_name = _safe_file_name(file_name)
            content_sha256 = _content_sha256(content)
            object_key = self._object_key(user.tenant_id, "staging", f"{upload_id}_{safe_file_name}")
            source_ref = self._storage.put(
                object_key,
                content,
                content_type=content_type or "application/octet-stream",
            )

            metadata_json: dict[str, object] = {
                "content_type": content_type or "application/octet-stream",
                "content_sha256": content_sha256,
            }
            if extra_metadata:
                metadata_json.update(extra_metadata)

            upload = StagedDocumentUpload(
                id=upload_id,
                tenant_id=user.tenant_id,
                owner_user_id=user.user_id,
                original_file_name=safe_file_name,
                source_type=_source_type_for_file(safe_file_name),
                source_path=source_ref,
                status="staged",
                size_bytes=len(content),
                expires_at=datetime.now(UTC) + timedelta(days=1),
                metadata_json=metadata_json,
            )
            session.add(upload)
            await session.commit()
            await session.refresh(upload)
            return upload

    async def cancel_staged_upload(
        self,
        *,
        user: UserContext,
        upload_id: str,
    ) -> bool:
        async with self._session_factory() as session:
            upload = await session.scalar(
                select(StagedDocumentUpload).where(
                    StagedDocumentUpload.tenant_id == user.tenant_id,
                    StagedDocumentUpload.id == upload_id,
                    StagedDocumentUpload.status == "staged",
                )
            )
            if upload is None:
                return False
            if upload.owner_user_id is not None and upload.owner_user_id != user.user_id and not user.is_admin:
                return False
            self._storage.delete(upload.source_path)
            upload.status = "cancelled"
            await session.commit()
            return True

    async def commit_bucket_documents(
        self,
        *,
        user: UserContext,
        bucket_id: str,
        staged_upload_ids: list[str],
        existing_document_ids: list[str],
        removed_document_ids: list[str],
        visibility: str = "private",
        allowed_roles: list[str] | None = None,
    ) -> tuple[list[DocumentAsset], list[str]] | None:
        async with self._session_factory() as session:
            bucket = await self._get_bucket(
                session=session,
                tenant_id=user.tenant_id,
                bucket_id=bucket_id,
            )
            if bucket is None:
                return None

            committed_documents: list[DocumentAsset] = []
            indexing_job_ids: list[str] = []
            normalized_allowed_roles = allowed_roles or []

            for document_id in _deduplicate_ids(removed_document_ids):
                link = await session.scalar(
                    select(BucketDocument).where(
                        BucketDocument.tenant_id == user.tenant_id,
                        BucketDocument.bucket_id == bucket_id,
                        BucketDocument.document_id == document_id,
                    )
                )
                if link is not None:
                    await session.delete(link)

            for document_id in _deduplicate_ids(existing_document_ids):
                document = await session.scalar(
                    select(DocumentAsset)
                    .options(selectinload(DocumentAsset.acl_entries))
                    .where(
                        DocumentAsset.tenant_id == user.tenant_id,
                        DocumentAsset.id == document_id,
                    )
                )
                if document is None:
                    continue
                if not can_read_document(document=document, user=user, acl_entries=document.acl_entries):
                    continue
                await self._ensure_bucket_document_link(
                    session=session,
                    user=user,
                    bucket_id=bucket_id,
                    document_id=document.id,
                    indexing_status="indexing",
                )
                job_id = str(uuid4())
                session.add(
                    DocumentIndexingJob(
                        id=job_id,
                        tenant_id=user.tenant_id,
                        bucket_id=bucket_id,
                        document_id=document.id,
                        status="pending",
                        metadata_json={"source": "bucket_existing_document_commit"},
                    )
                )
                committed_documents.append(document)
                indexing_job_ids.append(job_id)

            for upload_id in _deduplicate_ids(staged_upload_ids):
                upload = await session.scalar(
                    select(StagedDocumentUpload).where(
                        StagedDocumentUpload.tenant_id == user.tenant_id,
                        StagedDocumentUpload.id == upload_id,
                        StagedDocumentUpload.status == "staged",
                    )
                )
                if upload is None:
                    continue
                if upload.owner_user_id is not None and upload.owner_user_id != user.user_id and not user.is_admin:
                    continue

                existing_document = await _find_existing_uploaded_document(
                    session=session,
                    user=user,
                    upload=upload,
                )
                if existing_document is not None:
                    await self._ensure_bucket_document_link(
                        session=session,
                        user=user,
                        bucket_id=bucket_id,
                        document_id=existing_document.id,
                        indexing_status="indexed"
                        if existing_document.status == "indexed"
                        else "indexing",
                    )
                    if existing_document.status != "indexed":
                        job_id = str(uuid4())
                        session.add(
                            DocumentIndexingJob(
                                id=job_id,
                                tenant_id=user.tenant_id,
                                bucket_id=bucket_id,
                                document_id=existing_document.id,
                                status="pending",
                                metadata_json={"source": "bucket_existing_upload_dedup"},
                            )
                        )
                        indexing_job_ids.append(job_id)
                    self._storage.delete(upload.source_path)
                    upload.status = "committed"
                    upload.metadata_json = {
                        **dict(upload.metadata_json),
                        "document_id": existing_document.id,
                        "bucket_id": bucket_id,
                        "deduplicated": True,
                    }
                    committed_documents.append(existing_document)
                    continue

                document_id = str(uuid4())
                object_key = self._object_key(
                    user.tenant_id,
                    "documents",
                    f"{document_id}_{upload.original_file_name}",
                )
                source_ref = self._storage.move(upload.source_path, object_key)

                document = DocumentAsset(
                    id=document_id,
                    tenant_id=user.tenant_id,
                    owner_user_id=user.user_id,
                    title=upload.original_file_name,
                    file_name=upload.original_file_name,
                    source_type=upload.source_type,
                    source_path=source_ref,
                    status="indexing",
                    visibility=visibility,
                    allowed_roles=normalized_allowed_roles,
                    size_bytes=upload.size_bytes,
                    metadata_json=dict(upload.metadata_json),
                )
                session.add(document)
                await self._ensure_bucket_document_link(
                    session=session,
                    user=user,
                    bucket_id=bucket_id,
                    document_id=document_id,
                    indexing_status="indexing",
                )
                job_id = str(uuid4())
                session.add(
                    DocumentIndexingJob(
                        id=job_id,
                        tenant_id=user.tenant_id,
                        bucket_id=bucket_id,
                        document_id=document_id,
                        status="pending",
                        metadata_json={"source": "bucket_commit"},
                    )
                )
                upload.status = "committed"
                upload.metadata_json = {
                    **dict(upload.metadata_json),
                    "document_id": document_id,
                    "bucket_id": bucket_id,
                }
                committed_documents.append(document)
                indexing_job_ids.append(job_id)

            await session.commit()
            for document in committed_documents:
                await session.refresh(document)
            return committed_documents, indexing_job_ids

    async def commit_personal_documents(
        self,
        *,
        user: UserContext,
        staged_upload_ids: list[str],
        visibility: str = "private",
        allowed_roles: list[str] | None = None,
    ) -> tuple[list[DocumentAsset], list[str]]:
        async with self._session_factory() as session:
            committed_documents: list[DocumentAsset] = []
            indexing_job_ids: list[str] = []
            normalized_allowed_roles = allowed_roles or []

            for upload_id in _deduplicate_ids(staged_upload_ids):
                upload = await session.scalar(
                    select(StagedDocumentUpload).where(
                        StagedDocumentUpload.tenant_id == user.tenant_id,
                        StagedDocumentUpload.id == upload_id,
                        StagedDocumentUpload.status == "staged",
                    )
                )
                if upload is None:
                    continue
                if upload.owner_user_id is not None and upload.owner_user_id != user.user_id and not user.is_admin:
                    continue

                existing_document = await _find_existing_uploaded_document(
                    session=session,
                    user=user,
                    upload=upload,
                )
                if existing_document is not None:
                    self._storage.delete(upload.source_path)
                    upload.status = "committed"
                    upload.metadata_json = {
                        **dict(upload.metadata_json),
                        "document_id": existing_document.id,
                        "deduplicated": True,
                    }
                    committed_documents.append(existing_document)
                    continue

                document_id = str(uuid4())
                object_key = self._object_key(
                    user.tenant_id,
                    "documents",
                    f"{document_id}_{upload.original_file_name}",
                )
                source_ref = self._storage.move(upload.source_path, object_key)

                document = DocumentAsset(
                    id=document_id,
                    tenant_id=user.tenant_id,
                    owner_user_id=user.user_id,
                    title=upload.original_file_name,
                    file_name=upload.original_file_name,
                    source_type=upload.source_type,
                    source_path=source_ref,
                    status="indexing",
                    visibility=visibility,
                    allowed_roles=normalized_allowed_roles,
                    size_bytes=upload.size_bytes,
                    metadata_json=dict(upload.metadata_json),
                )
                session.add(document)
                job_id = str(uuid4())
                session.add(
                    DocumentIndexingJob(
                        id=job_id,
                        tenant_id=user.tenant_id,
                        bucket_id=PERSONAL_INDEX_BUCKET_ID,
                        document_id=document_id,
                        status="pending",
                        metadata_json={"source": "personal_commit"},
                    )
                )
                upload.status = "committed"
                upload.metadata_json = {
                    **dict(upload.metadata_json),
                    "document_id": document_id,
                }
                committed_documents.append(document)
                indexing_job_ids.append(job_id)

            await session.commit()
            for document in committed_documents:
                await session.refresh(document)
            return committed_documents, indexing_job_ids

    async def save_uploaded_document(
        self,
        *,
        user: UserContext,
        bucket_id: str | None,
        file_name: str,
        content: bytes,
        content_type: str | None,
        visibility: str = "private",
        allowed_roles: list[str] | None = None,
    ) -> DocumentAsset | None:
        async with self._session_factory() as session:
            if bucket_id is not None:
                bucket = await self._get_bucket(
                    session=session,
                    tenant_id=user.tenant_id,
                    bucket_id=bucket_id,
                )
                if bucket is None:
                    return None

            document_id = str(uuid4())
            safe_file_name = _safe_file_name(file_name)
            content_sha256 = _content_sha256(content)
            object_key = self._object_key(
                user.tenant_id,
                bucket_id or "personal",
                f"{document_id}_{safe_file_name}",
            )
            source_ref = self._storage.put(
                object_key,
                content,
                content_type=content_type or "application/octet-stream",
            )

            document = DocumentAsset(
                id=document_id,
                tenant_id=user.tenant_id,
                owner_user_id=user.user_id,
                title=safe_file_name,
                file_name=safe_file_name,
                source_type=_source_type_for_file(safe_file_name),
                source_path=source_ref,
                status="uploaded",
                visibility=visibility,
                allowed_roles=allowed_roles or [],
                size_bytes=len(content),
                metadata_json={
                    "content_type": content_type or "application/octet-stream",
                    "content_sha256": content_sha256,
                },
            )
            session.add(document)
            if bucket_id is not None:
                session.add(
                    BucketDocument(
                        tenant_id=user.tenant_id,
                        bucket_id=bucket_id,
                        document_id=document_id,
                        added_by_user_id=user.user_id,
                    )
                )
            await session.commit()
            await session.refresh(document)
            return document

    async def _ensure_bucket_document_link(
        self,
        *,
        session: AsyncSession,
        user: UserContext,
        bucket_id: str,
        document_id: str,
        indexing_status: str = "indexed",
    ) -> None:
        existing_link = await session.scalar(
            select(BucketDocument).where(
                BucketDocument.tenant_id == user.tenant_id,
                BucketDocument.bucket_id == bucket_id,
                BucketDocument.document_id == document_id,
            )
        )
        if existing_link is None:
            session.add(
                BucketDocument(
                    tenant_id=user.tenant_id,
                    bucket_id=bucket_id,
                    document_id=document_id,
                    added_by_user_id=user.user_id,
                    indexing_status=indexing_status,
                )
            )
        else:
            existing_link.indexing_status = indexing_status
            existing_link.indexing_error = None

    async def _get_bucket(
        self,
        *,
        session: AsyncSession,
        tenant_id: str,
        bucket_id: str,
    ) -> KnowledgeBucket | None:
        return await session.scalar(
            select(KnowledgeBucket).where(
                KnowledgeBucket.tenant_id == tenant_id,
                KnowledgeBucket.id == bucket_id,
            )
        )


def _safe_file_name(file_name: str) -> str:
    normalized = Path(file_name).name.strip()
    return normalized or "uploaded-file"


def _source_type_for_file(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower().lstrip(".")
    return suffix or "unknown"


def _content_sha256(content: bytes) -> str:
    return sha256(content).hexdigest()


async def _find_existing_uploaded_document(
    *,
    session: AsyncSession,
    user: UserContext,
    upload: StagedDocumentUpload,
) -> DocumentAsset | None:
    content_sha256 = str(upload.metadata_json.get("content_sha256") or "").strip()
    if not content_sha256:
        return None
    return await session.scalar(
        select(DocumentAsset)
        .where(
            DocumentAsset.tenant_id == user.tenant_id,
            DocumentAsset.owner_user_id == user.user_id,
            DocumentAsset.file_name == upload.original_file_name,
            DocumentAsset.size_bytes == upload.size_bytes,
            DocumentAsset.metadata_json["content_sha256"].astext == content_sha256,
        )
        .order_by(
            (DocumentAsset.status == "indexed").desc(),
            DocumentAsset.created_at.desc(),
        )
    )


def _deduplicate_available_documents(documents: list[DocumentAsset]) -> list[DocumentAsset]:
    by_key: dict[tuple[str | None, str, int, str], DocumentAsset] = {}
    for document in documents:
        content_sha256 = str(document.metadata_json.get("content_sha256") or "").strip()
        key = (
            document.owner_user_id,
            document.file_name,
            document.size_bytes,
            content_sha256 or f"size:{document.size_bytes}",
        )
        current = by_key.get(key)
        if current is None or _document_dedup_rank(document) > _document_dedup_rank(current):
            by_key[key] = document
    return sorted(by_key.values(), key=lambda document: document.created_at, reverse=True)


def _document_dedup_rank(document: DocumentAsset) -> tuple[int, int, datetime]:
    status_rank = {
        "indexed": 3,
        "indexing": 2,
        "uploaded": 1,
        "index_failed": 0,
    }.get(document.status, 0)
    bucket_rank = 1 if document.bucket_links else 0
    return status_rank, bucket_rank, document.created_at


def _deduplicate_ids(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result
