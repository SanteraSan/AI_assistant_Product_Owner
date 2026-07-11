from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import BucketDocument, DocumentAsset, KnowledgeBucket
from app.services.access_policy import UserContext, can_read_document


class BucketService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        raw_data_dir: str,
    ) -> None:
        self._session_factory = session_factory
        self._upload_root = _resolve_upload_root(raw_data_dir)

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
    ) -> list[DocumentAsset] | None:
        async with self._session_factory() as session:
            bucket = await self._get_bucket(
                session=session,
                tenant_id=user.tenant_id,
                bucket_id=bucket_id,
            )
            if bucket is None:
                return None
            result = await session.execute(
                select(DocumentAsset)
                .join(BucketDocument, BucketDocument.document_id == DocumentAsset.id)
                .options(selectinload(DocumentAsset.acl_entries))
                .where(
                    BucketDocument.tenant_id == user.tenant_id,
                    BucketDocument.bucket_id == bucket_id,
                    DocumentAsset.tenant_id == user.tenant_id,
                )
                .order_by(BucketDocument.created_at.desc())
            )
            documents = list(result.scalars())
            return [
                document
                for document in documents
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
                .options(selectinload(DocumentAsset.acl_entries))
                .where(DocumentAsset.tenant_id == user.tenant_id)
                .order_by(DocumentAsset.created_at.desc())
            )
            documents = list(result.scalars())
            return [
                document
                for document in documents
                if can_read_document(
                    document=document,
                    user=user,
                    acl_entries=document.acl_entries,
                )
            ]

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
            target_dir = self._upload_root / user.tenant_id / (bucket_id or "personal")
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = target_dir / f"{document_id}_{safe_file_name}"
            target_path.write_bytes(content)

            document = DocumentAsset(
                id=document_id,
                tenant_id=user.tenant_id,
                owner_user_id=user.user_id,
                title=safe_file_name,
                file_name=safe_file_name,
                source_type=_source_type_for_file(safe_file_name),
                source_path=str(target_path),
                status="uploaded",
                visibility=visibility,
                allowed_roles=allowed_roles or [],
                size_bytes=len(content),
                metadata_json={"content_type": content_type or "application/octet-stream"},
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


def _resolve_upload_root(raw_data_dir: str) -> Path:
    raw_path = Path(raw_data_dir)
    if not raw_path.is_absolute():
        backend_root = Path(__file__).resolve().parents[2]
        raw_path = backend_root / raw_path
    return (raw_path / "uploads").resolve()


def _safe_file_name(file_name: str) -> str:
    normalized = Path(file_name).name.strip()
    return normalized or "uploaded-file"


def _source_type_for_file(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower().lstrip(".")
    return suffix or "unknown"
