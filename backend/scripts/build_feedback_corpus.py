#!/usr/bin/env python3
"""Assemble the v1 feedback corpus and optionally seed Postgres.

JSONL is the default output. Postgres runs only with --seed and never
substitutes settings.default_tenant_id. The script does not create a
bucket, call init_db, or open holdout.jsonl for writing.

``--index-attached`` binds this bucket's ``fb-v1-`` rows to one product
document and calls ``DocumentIndexingService.process_jobs``. It does not
publish ``indexing.requested`` and does not recreate Qdrant collections.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.feedback_rules import (  # noqa: E402
    CORPUS_ID_PREFIX,
    FeedbackCleanedRow,
    assemble_raw_rows,
    apply_feedback_rules,
    assert_cleaned_rows_match_frozen,
    assert_no_holdout_texts,
    feedback_product_document_id,
    seed_feedback_items,
    write_corpus_files,
)

DEFAULT_SOURCE_DIR = Path("/home/santera/ML|LLM|RAG/sintetic_data")
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "feedback" / "v1"
_CLASS_ORDER = ("noise", "churn_signal", "bug", "feature")
_PRODUCT_OWNER_USER_ID = "system-seed"
_EVAL_COLLECTION_NAME = "feedback_eval_v1"
_FORBIDDEN_MARKERS = ("Класс!", "Удаляю")
_SCROLL_PAGE = 256
_SCROLL_PAGE_CAP = 100
_EXPECTED_POSTGRES = {"noise": 350, "churn_signal": 75, "bug": 68, "feature": 17}
_EXPECTED_INDEX_TRUE = {"bug": 60, "feature": 15}
_EXPECTED_CHUNKS = 75


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the v1 feedback corpus.")
    parser.add_argument("--write-jsonl", action="store_true", help="Write raw, cleaned, manifest, and rule_report.")
    parser.add_argument("--seed", action="store_true", help="Replace this tenant/bucket fb-v1 rows in Postgres.")
    parser.add_argument(
        "--index-attached",
        action="store_true",
        help="Bind this bucket's fb-v1 rows to the product document and run process_jobs.",
    )
    parser.add_argument("--tenant-id", default=None)
    parser.add_argument("--bucket-id", default=None)
    parser.add_argument("--noise-path", type=Path, default=DEFAULT_SOURCE_DIR / "noise.jsonl")
    parser.add_argument("--churn-path", type=Path, default=DEFAULT_SOURCE_DIR / "churn.jsonl")
    parser.add_argument("--bugs-path", type=Path, default=DEFAULT_SOURCE_DIR / "bugs.jsonl")
    parser.add_argument("--features-path", type=Path, default=DEFAULT_SOURCE_DIR / "features.jsonl")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--holdout-path", type=Path, default=DEFAULT_OUT_DIR / "holdout.jsonl")
    args = parser.parse_args()

    if not args.write_jsonl and not args.seed and not args.index_attached:
        raise SystemExit("Pass --write-jsonl. Postgres runs only with --seed or --index-attached.")

    tenant_id = (args.tenant_id or "").strip()
    bucket_id = (args.bucket_id or "").strip()
    if args.seed and (not tenant_id or not bucket_id):
        raise SystemExit("--seed requires --tenant-id and --bucket-id")
    if args.index_attached and (not tenant_id or not bucket_id):
        raise SystemExit("--index-attached requires --tenant-id and --bucket-id")

    cleaned_rows: Sequence[FeedbackCleanedRow] | None = None
    if args.write_jsonl or args.seed:
        raw_rows = assemble_raw_rows(
            noise_path=args.noise_path,
            churn_path=args.churn_path,
            bugs_path=args.bugs_path,
            features_path=args.features_path,
        )
        cleaned_rows = apply_feedback_rules(raw_rows)
        _print_summary(cleaned_rows)
        if args.seed and args.index_attached:
            _assert_ready_to_index(cleaned_rows, args.out_dir / "cleaned.jsonl", args.holdout_path)
        if args.write_jsonl:
            write_corpus_files(
                out_dir=args.out_dir,
                raw_rows=raw_rows,
                cleaned_rows=cleaned_rows,
                holdout_path=args.holdout_path,
            )
            print(f"wrote {args.out_dir}")
    if args.index_attached:
        asyncio.run(
            _index_attached(
                tenant_id,
                bucket_id,
                cleaned_rows=cleaned_rows if args.seed else None,
                cleaned_path=args.out_dir / "cleaned.jsonl",
                holdout_path=args.holdout_path,
            )
        )
    elif args.seed:
        if cleaned_rows is None:
            raise SystemExit("--seed requires an assembled corpus")
        asyncio.run(_seed(tenant_id, bucket_id, cleaned_rows))


def _print_summary(rows: Sequence[FeedbackCleanedRow]) -> None:
    counts = {name: 0 for name in _CLASS_ORDER}
    indexed = {"bug": 0, "feature": 0}
    mismatch = 0
    for row in rows:
        counts[row.rule_class] = counts.get(row.rule_class, 0) + 1
        if row.index_in_rag and row.rule_class in indexed:
            indexed[row.rule_class] += 1
        if row.rule_class != row.source.generator_class:
            mismatch += 1
    print(
        f"rows={len(rows)} "
        f"noise={counts['noise']} churn_signal={counts['churn_signal']} "
        f"bug={counts['bug']} feature={counts['feature']} "
        f"index_true={indexed['bug'] + indexed['feature']} "
        f"bug_indexed={indexed['bug']} feature_indexed={indexed['feature']} "
        f"mismatch={mismatch}"
    )


async def _seed(tenant_id: str, bucket_id: str, cleaned_rows: Sequence[FeedbackCleanedRow]) -> None:
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.db.models import KnowledgeBucket
    from app.db.session import create_engine, create_session_factory

    engine = create_engine(get_settings().postgres_dsn)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                select(KnowledgeBucket.tenant_id).where(KnowledgeBucket.id == bucket_id)
            )
            bucket_tenant = result.scalar_one_or_none()
            await connection.rollback()
        if bucket_tenant != tenant_id:
            raise SystemExit(
                "Bucket does not exist or knowledge_buckets.tenant_id does not match --tenant-id."
            )
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            async with session.begin():
                inserted = await seed_feedback_items(
                    session,
                    tenant_id=tenant_id,
                    bucket_id=bucket_id,
                    cleaned_rows=cleaned_rows,
                )
        print(f"seeded {inserted} feedback items")
    finally:
        await engine.dispose()


def _assert_ready_to_index(
    rows: Sequence[FeedbackCleanedRow],
    cleaned_path: Path,
    holdout_path: Path,
) -> None:
    try:
        assert_cleaned_rows_match_frozen(rows, cleaned_path)
        assert_no_holdout_texts(rows, holdout_path)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _holdout_texts(path: Path) -> set[str]:
    texts: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        text = payload.get("text") if isinstance(payload, dict) else None
        if isinstance(text, str):
            texts.add(text)
    return texts


def _bucket_filter(tenant_id: str, bucket_id: str):
    from qdrant_client.http import models as qmodels

    return qmodels.Filter(
        must=[
            qmodels.FieldCondition(key="tenant_id", match=qmodels.MatchValue(value=tenant_id)),
            qmodels.FieldCondition(key="bucket_id", match=qmodels.MatchValue(value=bucket_id)),
        ]
    )


def _feedback_filter(tenant_id: str, bucket_id: str):
    from qdrant_client.http import models as qmodels

    feedback = qmodels.FieldCondition(key="source_type", match=qmodels.MatchValue(value="feedback"))
    bucket_filter = _bucket_filter(tenant_id, bucket_id)
    return qmodels.Filter(must=[*bucket_filter.must, feedback])


def _collection_size(client, collection_name: str, query_filter=None) -> int | None:
    if not client.collection_exists(collection_name):
        return None
    counted = client.count(
        collection_name=collection_name,
        count_filter=query_filter,
        exact=True,
    )
    return int(counted.count)


def _scroll_feedback_payloads(client, collection_name: str, tenant_id: str, bucket_id: str) -> list[dict[str, object]]:
    if not client.collection_exists(collection_name):
        return []
    payloads: list[dict[str, object]] = []
    offset = None
    seen: set[str] = set()
    for _page in range(_SCROLL_PAGE_CAP):
        records, offset = client.scroll(
            collection_name=collection_name,
            scroll_filter=_feedback_filter(tenant_id, bucket_id),
            limit=_SCROLL_PAGE,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for record in records:
            raw = record.payload or {}
            payloads.append(dict(raw))
        if offset is None or not records:
            return payloads
        token = str(offset)
        if token in seen:
            raise RuntimeError("qdrant scroll offset did not advance")
        seen.add(token)
    raise RuntimeError("qdrant scroll page cap reached")


def _payload_blob(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _count_label(value: int | None) -> str:
    if value is None:
        return "missing"
    return str(value)


def _redact(text: str) -> str:
    flat = " ".join(text.split())
    if "postgresql" in flat or "asyncpg" in flat:
        return "database error redacted"
    return flat


async def _index_attached(
    tenant_id: str,
    bucket_id: str,
    *,
    cleaned_rows: Sequence[FeedbackCleanedRow] | None,
    cleaned_path: Path,
    holdout_path: Path,
) -> None:
    from qdrant_client import QdrantClient
    from sqlalchemy import func, or_, select

    from app.core.config import get_settings
    from app.db.models import (
        BucketDocument,
        DocumentAsset,
        DocumentIndexingJob,
        FeedbackItem,
        KnowledgeBucket,
    )
    from app.db.session import create_engine, create_session_factory
    from app.services.document_indexing_service import (
        DocumentIndexingService,
        assert_product_qdrant_target,
        ensure_feedback_product_document,
        enqueue_feedback_product_job,
        open_product_qdrant_store,
    )
    from app.services.feedback_rules import bind_feedback_items_to_document
    from app.services.ollama_client import OllamaClient
    from app.services.ollama_load_guard import OllamaLoadGuard

    settings = get_settings()
    try:
        assert_product_qdrant_target(
            collection_name=settings.qdrant_collection,
            embedding_model=settings.embedding_model,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    document_id = feedback_product_document_id(tenant_id=tenant_id, bucket_id=bucket_id)
    cleaned_before = _file_sha256(cleaned_path)
    holdout_before = _file_sha256(holdout_path)
    holdout_texts = _holdout_texts(holdout_path)

    engine = create_engine(settings.postgres_dsn)
    probe = None
    ollama_client = None
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            bucket_tenant = await session.scalar(
                select(KnowledgeBucket.tenant_id).where(KnowledgeBucket.id == bucket_id)
            )
            if bucket_tenant != tenant_id:
                raise SystemExit(
                    "Bucket does not exist or knowledge_buckets.tenant_id does not match --tenant-id."
                )
            foreign = await session.scalar(
                select(func.count())
                .select_from(FeedbackItem)
                .where(
                    FeedbackItem.tenant_id == tenant_id,
                    FeedbackItem.bucket_id == bucket_id,
                    or_(
                        FeedbackItem.corpus_id.is_(None),
                        ~FeedbackItem.corpus_id.like(f"{CORPUS_ID_PREFIX}%"),
                    ),
                )
            )
            loaded = await session.scalar(
                select(func.count())
                .select_from(FeedbackItem)
                .where(
                    FeedbackItem.tenant_id == tenant_id,
                    FeedbackItem.bucket_id == bucket_id,
                    FeedbackItem.corpus_id.like(f"{CORPUS_ID_PREFIX}%"),
                )
            )
            await session.rollback()
        if int(foreign or 0) > 0:
            raise SystemExit(
                "feedback_items in this bucket include corpus_id outside fb-v1- or NULL; refusing to delete"
            )
        if cleaned_rows is None and int(loaded or 0) == 0:
            raise SystemExit("no fb-v1 feedback items in this bucket; pass --seed --index-attached")

        probe = QdrantClient(
            url=settings.qdrant_url,
            check_compatibility=settings.qdrant_check_compatibility,
        )
        eval_before = _collection_size(probe, _EVAL_COLLECTION_NAME)
        bucket_before = _collection_size(
            probe,
            settings.qdrant_collection,
            _bucket_filter(tenant_id, bucket_id),
        )
        try:
            existing_points = _scroll_feedback_payloads(
                probe,
                settings.qdrant_collection,
                tenant_id,
                bucket_id,
            )
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc
        foreign_points = [
            payload
            for payload in existing_points
            if str(payload.get("document_id") or "") != document_id
        ]
        if foreign_points:
            example = foreign_points[0].get("document_id")
            raise SystemExit(
                f"{len(foreign_points)} feedback points use another document_id ({example}); "
                "refusing to delete them"
            )
        print(f"feedback_eval_v1_points_before={_count_label(eval_before)}", flush=True)
        print(f"documents_bucket_points_before={_count_label(bucket_before)}", flush=True)

        inserted: int | None = None
        async with session_factory() as session:
            async with session.begin():
                if cleaned_rows is not None:
                    inserted = await seed_feedback_items(
                        session,
                        tenant_id=tenant_id,
                        bucket_id=bucket_id,
                        cleaned_rows=cleaned_rows,
                    )
                await ensure_feedback_product_document(
                    session,
                    tenant_id=tenant_id,
                    bucket_id=bucket_id,
                    document_id=document_id,
                    owner_user_id=_PRODUCT_OWNER_USER_ID,
                )
                bound = await bind_feedback_items_to_document(
                    session,
                    tenant_id=tenant_id,
                    bucket_id=bucket_id,
                    document_id=document_id,
                )
                if bound < 0:
                    bound = int(
                        await session.scalar(
                            select(func.count())
                            .select_from(FeedbackItem)
                            .where(
                                FeedbackItem.tenant_id == tenant_id,
                                FeedbackItem.bucket_id == bucket_id,
                                FeedbackItem.document_id == document_id,
                                FeedbackItem.corpus_id.like(f"{CORPUS_ID_PREFIX}%"),
                            )
                        )
                        or 0
                    )
                if bound <= 0:
                    raise SystemExit("no fb-v1 rows were bound")
                job_id = await enqueue_feedback_product_job(
                    session,
                    tenant_id=tenant_id,
                    bucket_id=bucket_id,
                    document_id=document_id,
                    owner_user_id=_PRODUCT_OWNER_USER_ID,
                )
        if inserted is not None:
            print(f"seeded {inserted} feedback items", flush=True)
        print(f"document_id={document_id}", flush=True)
        print(f"job_id={job_id}", flush=True)
        print(f"bound={bound}", flush=True)
        print("process_jobs=started", flush=True)

        ollama_client = OllamaClient(
            base_url=settings.ollama_base_url,
            timeout_seconds=settings.request_timeout_seconds,
            load_guard=OllamaLoadGuard(
                max_concurrency=settings.ollama_max_concurrency,
                timeout_seconds=settings.ollama_queue_timeout_seconds,
            ),
        )
        qdrant_store = open_product_qdrant_store(
            url=settings.qdrant_url,
            collection_name=settings.qdrant_collection,
            embedding_model=settings.embedding_model,
            check_compatibility=settings.qdrant_check_compatibility,
        )
        indexing_service = DocumentIndexingService(
            session_factory=session_factory,
            qdrant_store=qdrant_store,
            ollama_client=ollama_client,
            embedding_model=settings.embedding_model,
            image_vision_enabled=settings.image_vision_enabled,
            image_vision_model=settings.image_vision_model,
            event_publisher=None,
        )
        # Same method as scripts/run_indexing_worker.py. No Kafka event.
        # process_jobs calls ensure_collection(..., recreate=False).
        process_error: str | None = None
        try:
            await indexing_service.process_jobs([job_id], message_tenant_id=tenant_id)
        except Exception as exc:
            process_error = _redact(str(exc))
            print(f"process_jobs_error={process_error}", flush=True)

        problems: list[str] = []
        if process_error:
            problems.append(process_error)
        async with session_factory() as session:
            bucket_name = await session.scalar(
                select(KnowledgeBucket.name).where(
                    KnowledgeBucket.id == bucket_id,
                    KnowledgeBucket.tenant_id == tenant_id,
                )
            )
            job = await session.scalar(
                select(DocumentIndexingJob).where(DocumentIndexingJob.id == job_id)
            )
            document = await session.scalar(
                select(DocumentAsset).where(DocumentAsset.id == document_id)
            )
            link = await session.scalar(
                select(BucketDocument).where(
                    BucketDocument.tenant_id == tenant_id,
                    BucketDocument.bucket_id == bucket_id,
                    BucketDocument.document_id == document_id,
                )
            )
            grouped = (
                await session.execute(
                    select(FeedbackItem.feedback_class, FeedbackItem.index_in_rag, func.count())
                    .where(
                        FeedbackItem.tenant_id == tenant_id,
                        FeedbackItem.bucket_id == bucket_id,
                        FeedbackItem.corpus_id.like(f"{CORPUS_ID_PREFIX}%"),
                    )
                    .group_by(FeedbackItem.feedback_class, FeedbackItem.index_in_rag)
                )
            ).all()
            mismatch = await session.scalar(
                select(func.count())
                .select_from(FeedbackItem)
                .where(
                    FeedbackItem.tenant_id == tenant_id,
                    FeedbackItem.bucket_id == bucket_id,
                    FeedbackItem.corpus_id.like(f"{CORPUS_ID_PREFIX}%"),
                    or_(
                        FeedbackItem.document_id.is_(None),
                        FeedbackItem.document_id != document_id,
                    ),
                )
            )
            bodies = (
                await session.scalars(
                    select(FeedbackItem.body).where(
                        FeedbackItem.tenant_id == tenant_id,
                        FeedbackItem.bucket_id == bucket_id,
                        FeedbackItem.corpus_id.like(f"{CORPUS_ID_PREFIX}%"),
                    )
                )
            ).all()
            job_status = job.status if job is not None else "missing"
            chunks_indexed = int(job.chunks_indexed) if job is not None else None
            failed_stage = job.failed_stage if job is not None else None
            job_error = job.error if job is not None else None
            document_status = document.status if document is not None else "missing"
            link_status = link.indexing_status if link is not None else "missing"
            bucket_name_value = bucket_name
            mismatch_value = int(mismatch or 0)
            await session.rollback()

        class_counts = {name: 0 for name in _CLASS_ORDER}
        index_true = {name: 0 for name in _EXPECTED_INDEX_TRUE}
        unknown_class = 0
        for label, flag, count in grouped:
            amount = int(count)
            if label in class_counts:
                class_counts[label] += amount
            else:
                unknown_class += amount
            if flag and label in index_true:
                index_true[label] += amount
        postgres_total = sum(class_counts.values())
        holdout_body_hits = sum(1 for body in bodies if body in holdout_texts)
        print(f"bucket_name={bucket_name_value}", flush=True)
        print(f"document_id={document_id}", flush=True)
        print(f"job_id={job_id}", flush=True)
        print(f"job_status={job_status}", flush=True)
        print(f"chunks_indexed={chunks_indexed}", flush=True)
        if failed_stage:
            print(f"failed_stage={failed_stage}", flush=True)
        if job_error:
            print(f"job_error={_redact(job_error)}", flush=True)
        print(f"document_status={document_status}", flush=True)
        print(f"link_indexing_status={link_status}", flush=True)
        print(f"postgres_fb_v1={postgres_total}", flush=True)
        for name in _CLASS_ORDER:
            print(f"postgres_{name}={class_counts[name]}", flush=True)
        print(f"postgres_index_true_bug={index_true['bug']}", flush=True)
        print(f"postgres_index_true_feature={index_true['feature']}", flush=True)
        print(f"postgres_document_id_mismatch={mismatch_value}", flush=True)
        print(f"postgres_holdout_body_hits={holdout_body_hits}", flush=True)

        eval_after = _collection_size(probe, _EVAL_COLLECTION_NAME)
        bucket_after = _collection_size(
            probe,
            settings.qdrant_collection,
            _bucket_filter(tenant_id, bucket_id),
        )
        try:
            points = _scroll_feedback_payloads(
                probe,
                settings.qdrant_collection,
                tenant_id,
                bucket_id,
            )
        except RuntimeError as exc:
            points = []
            problems.append(str(exc))
        class_points: Counter[str] = Counter()
        index_false = 0
        synthetic_false = 0
        document_mismatch = 0
        forbidden_hits = 0
        holdout_content_hits = 0
        for payload in points:
            label = str(payload.get("feedback_class") or "")
            class_points[label] += 1
            if payload.get("index_in_rag") is not True:
                index_false += 1
            if payload.get("synthetic") is not True:
                synthetic_false += 1
            if str(payload.get("document_id") or "") != document_id:
                document_mismatch += 1
            blob = _payload_blob(payload)
            if any(marker in blob for marker in _FORBIDDEN_MARKERS):
                forbidden_hits += 1
            content = payload.get("content")
            if isinstance(content, str) and content in holdout_texts:
                holdout_content_hits += 1
        print(f"qdrant_collection={settings.qdrant_collection}", flush=True)
        print(f"embedding_model={settings.embedding_model}", flush=True)
        print(f"qdrant_feedback_points={len(points)}", flush=True)
        print(f"qdrant_bug={class_points.get('bug', 0)}", flush=True)
        print(f"qdrant_feature={class_points.get('feature', 0)}", flush=True)
        print(f"qdrant_noise={class_points.get('noise', 0)}", flush=True)
        print(f"qdrant_churn_signal={class_points.get('churn_signal', 0)}", flush=True)
        other = sum(
            count
            for label, count in class_points.items()
            if label not in {"bug", "feature", "noise", "churn_signal"}
        )
        print(f"qdrant_other_class={other}", flush=True)
        print(f"qdrant_index_in_rag_false={index_false}", flush=True)
        print(f"qdrant_synthetic_false={synthetic_false}", flush=True)
        print(f"qdrant_document_id_mismatch={document_mismatch}", flush=True)
        print(f"qdrant_forbidden_substring_hits={forbidden_hits}", flush=True)
        print(f"qdrant_holdout_content_hits={holdout_content_hits}", flush=True)
        print(f"feedback_eval_v1_points_after={_count_label(eval_after)}", flush=True)
        print(f"documents_bucket_points_after={_count_label(bucket_after)}", flush=True)
        cleaned_after = _file_sha256(cleaned_path)
        holdout_after = _file_sha256(holdout_path)
        print(f"cleaned_sha256={cleaned_after}", flush=True)
        print(f"holdout_sha256={holdout_after}", flush=True)

        if job_status != "completed" or chunks_indexed != _EXPECTED_CHUNKS:
            problems.append(f"job_status={job_status} chunks_indexed={chunks_indexed}")
        if document_status != "indexed" or link_status != "indexed":
            problems.append(f"document_status={document_status} link_indexing_status={link_status}")
        if class_counts != _EXPECTED_POSTGRES or postgres_total != 510 or unknown_class != 0:
            problems.append(
                f"postgres_counts={class_counts} total={postgres_total} unknown={unknown_class}"
            )
        if index_true != _EXPECTED_INDEX_TRUE:
            problems.append(f"postgres_index_true={index_true}")
        if mismatch_value != 0 or holdout_body_hits != 0:
            problems.append(
                f"postgres_document_id_mismatch={mismatch_value} "
                f"postgres_holdout_body_hits={holdout_body_hits}"
            )
        if (
            len(points) != _EXPECTED_CHUNKS
            or class_points.get("bug", 0) != 60
            or class_points.get("feature", 0) != 15
            or class_points.get("noise", 0) != 0
            or class_points.get("churn_signal", 0) != 0
            or other != 0
            or index_false != 0
            or synthetic_false != 0
            or document_mismatch != 0
            or forbidden_hits != 0
            or holdout_content_hits != 0
        ):
            problems.append(f"qdrant_feedback_points={len(points)}")
        if eval_before != eval_after:
            problems.append(
                "feedback_eval_v1_points "
                f"before={_count_label(eval_before)} after={_count_label(eval_after)}"
            )
        if cleaned_before != cleaned_after or holdout_before != holdout_after:
            problems.append("cleaned.jsonl or holdout.jsonl changed")
        if problems:
            print("index_attached_ok=false", flush=True)
            for problem in problems:
                print(f"problem={problem}", flush=True)
            raise SystemExit(1)
        print("index_attached_ok=true", flush=True)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"index_attached_error={_redact(str(exc))}", flush=True)
        raise SystemExit(1) from None
    finally:
        if ollama_client is not None:
            await ollama_client.aclose()
        if probe is not None:
            probe.close()
        await engine.dispose()


if __name__ == "__main__":
    main()
