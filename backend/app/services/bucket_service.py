from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import DocumentRecord, KnowledgeBucket


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
                select(KnowledgeBucket, func.count(DocumentRecord.id))
                .outerjoin(DocumentRecord, DocumentRecord.bucket_id == KnowledgeBucket.id)
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
        tenant_id: str,
        bucket_id: str,
    ) -> list[DocumentRecord] | None:
        async with self._session_factory() as session:
            bucket = await self._get_bucket(
                session=session,
                tenant_id=tenant_id,
                bucket_id=bucket_id,
            )
            if bucket is None:
                return None
            result = await session.execute(
                select(DocumentRecord)
                .where(
                    DocumentRecord.tenant_id == tenant_id,
                    DocumentRecord.bucket_id == bucket_id,
                )
                .order_by(DocumentRecord.created_at.desc())
            )
            return list(result.scalars())

    async def get_document(
        self,
        *,
        tenant_id: str,
        document_id: str,
    ) -> DocumentRecord | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(DocumentRecord).where(
                    DocumentRecord.tenant_id == tenant_id,
                    DocumentRecord.id == document_id,
                )
            )

    async def save_uploaded_document(
        self,
        *,
        tenant_id: str,
        bucket_id: str,
        file_name: str,
        content: bytes,
        content_type: str | None,
    ) -> DocumentRecord | None:
        async with self._session_factory() as session:
            bucket = await self._get_bucket(
                session=session,
                tenant_id=tenant_id,
                bucket_id=bucket_id,
            )
            if bucket is None:
                return None

            document_id = str(uuid4())
            safe_file_name = _safe_file_name(file_name)
            target_dir = self._upload_root / tenant_id / bucket_id
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = target_dir / f"{document_id}_{safe_file_name}"
            target_path.write_bytes(content)

            document = DocumentRecord(
                id=document_id,
                tenant_id=tenant_id,
                bucket_id=bucket_id,
                file_name=safe_file_name,
                source_type=_source_type_for_file(safe_file_name),
                source_path=str(target_path),
                status="uploaded",
                size_bytes=len(content),
                metadata_json={"content_type": content_type or "application/octet-stream"},
            )
            session.add(document)
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
