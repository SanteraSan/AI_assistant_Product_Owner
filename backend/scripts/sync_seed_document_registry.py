#!/usr/bin/env python3
"""Register Qdrant seed corpus files into Postgres document_assets + buckets.

Seed ingest writes path-based document_ids into Qdrant, while E1 ACL filters by
document_assets UUIDs. This script bridges them via source_path:

- create KnowledgeBucket rows for taskflow_seed / bucket_alpha / bucket_beta
- upsert DocumentAsset per unique (tenant_id, bucket_id, source_path)
- link assets into buckets

After sync, RAG ACL can match seed points by source_path (see allowed_source_paths).
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from pathlib import Path

from qdrant_client import QdrantClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import BucketDocument, DocumentAsset, KnowledgeBucket
from app.db.session import create_engine, create_session_factory, init_db


BUCKET_NAMES = {
    "taskflow_seed": "TaskFlow seed corpus",
    "bucket_alpha": "Bucket Alpha isolation fixture",
    "bucket_beta": "Bucket Beta isolation fixture",
    "sales_northwind": "Northwind Sales Demo",
    "sales_aurora": "Aurora Sales Demo",
}


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.postgres_dsn)
    await init_db(engine)
    session_factory = create_session_factory(engine)

    client = QdrantClient(url=settings.qdrant_url)
    pairs: dict[tuple[str, str, str], dict[str, str]] = {}
    offset = None
    while True:
        batch, offset = client.scroll(
            collection_name=settings.qdrant_collection,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in batch:
            payload = point.payload or {}
            tenant_id = str(payload.get("tenant_id") or "").strip()
            bucket_id = str(payload.get("bucket_id") or "").strip()
            source_path = str(payload.get("source_path") or "").strip()
            if not tenant_id or not bucket_id or not source_path:
                continue
            key = (tenant_id, bucket_id, source_path)
            if key in pairs:
                continue
            pairs[key] = {
                "source_type": str(payload.get("source_type") or "seed"),
                "title": str(payload.get("title") or Path(source_path).name),
            }
        if offset is None:
            break

    created_buckets = 0
    created_docs = 0
    linked = 0
    by_bucket: dict[str, int] = defaultdict(int)

    async with session_factory() as session:
        for bucket_id, name in BUCKET_NAMES.items():
            existing = await session.scalar(
                select(KnowledgeBucket).where(
                    KnowledgeBucket.tenant_id == settings.default_tenant_id,
                    KnowledgeBucket.id == bucket_id,
                )
            )
            if existing is None:
                session.add(
                    KnowledgeBucket(
                        id=bucket_id,
                        tenant_id=settings.default_tenant_id,
                        name=name,
                        description="Synced from Qdrant seed corpus for ACL/RAG evals",
                        owner_user_id="system-seed",
                        status="ready",
                        metadata_json={"origin": "sync_seed_document_registry"},
                    )
                )
                created_buckets += 1

        for (tenant_id, bucket_id, source_path), meta in pairs.items():
            if bucket_id not in BUCKET_NAMES and bucket_id != settings.default_bucket_id:
                # Still register unknown seed buckets so ACL scope stays complete.
                existing_bucket = await session.scalar(
                    select(KnowledgeBucket).where(
                        KnowledgeBucket.tenant_id == tenant_id,
                        KnowledgeBucket.id == bucket_id,
                    )
                )
                if existing_bucket is None:
                    session.add(
                        KnowledgeBucket(
                            id=bucket_id,
                            tenant_id=tenant_id,
                            name=f"Seed bucket {bucket_id}",
                            description="Auto-created from Qdrant seed payloads",
                            owner_user_id="system-seed",
                            status="ready",
                            metadata_json={"origin": "sync_seed_document_registry"},
                        )
                    )
                    created_buckets += 1

            document_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{tenant_id}:{bucket_id}:{source_path}"))
            document = await session.scalar(
                select(DocumentAsset).where(DocumentAsset.id == document_id)
            )
            if document is None:
                # Prefer existing upload asset with same source_path when present.
                document = await session.scalar(
                    select(DocumentAsset).where(
                        DocumentAsset.tenant_id == tenant_id,
                        DocumentAsset.source_path == source_path,
                    )
                )
            if document is None:
                file_name = Path(source_path).name
                document = DocumentAsset(
                    id=document_id,
                    tenant_id=tenant_id,
                    owner_user_id="system-seed",
                    title=meta["title"][:512],
                    file_name=file_name[:512],
                    source_type=meta["source_type"][:64],
                    source_path=source_path,
                    status="indexed",
                    visibility="tenant",
                    allowed_roles=[],
                    size_bytes=0,
                    metadata_json={"origin": "sync_seed_document_registry", "bucket_id": bucket_id},
                )
                session.add(document)
                created_docs += 1
            else:
                document.status = "indexed"
                if document.visibility == "private" and document.owner_user_id == "system-seed":
                    document.visibility = "tenant"

            link = await session.scalar(
                select(BucketDocument).where(
                    BucketDocument.tenant_id == tenant_id,
                    BucketDocument.bucket_id == bucket_id,
                    BucketDocument.document_id == document.id,
                )
            )
            if link is None:
                session.add(
                    BucketDocument(
                        tenant_id=tenant_id,
                        bucket_id=bucket_id,
                        document_id=document.id,
                        added_by_user_id="system-seed",
                        indexing_status="indexed",
                    )
                )
                linked += 1
            by_bucket[bucket_id] += 1

        await session.commit()

    await engine.dispose()
    print(
        {
            "pairs": len(pairs),
            "created_buckets": created_buckets,
            "created_docs": created_docs,
            "linked": linked,
            "by_bucket": dict(by_bucket),
        }
    )


if __name__ == "__main__":
    asyncio.run(main())
