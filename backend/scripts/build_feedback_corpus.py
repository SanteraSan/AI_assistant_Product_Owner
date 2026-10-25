#!/usr/bin/env python3
"""Assemble the v1 feedback corpus and optionally seed Postgres.

JSONL is the default output. Postgres runs only with --seed and never
substitutes settings.default_tenant_id. The script does not create a
bucket, call init_db, or open holdout.jsonl for writing.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.feedback_rules import (  # noqa: E402
    FeedbackCleanedRow,
    assemble_raw_rows,
    apply_feedback_rules,
    seed_feedback_items,
    write_corpus_files,
)

DEFAULT_SOURCE_DIR = Path("/home/santera/ML|LLM|RAG/sintetic_data")
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "feedback" / "v1"
_CLASS_ORDER = ("noise", "churn_signal", "bug", "feature")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the v1 feedback corpus.")
    parser.add_argument("--write-jsonl", action="store_true", help="Write raw, cleaned, manifest, and rule_report.")
    parser.add_argument("--seed", action="store_true", help="Replace this tenant/bucket fb-v1 rows in Postgres.")
    parser.add_argument("--tenant-id", default=None)
    parser.add_argument("--bucket-id", default=None)
    parser.add_argument("--noise-path", type=Path, default=DEFAULT_SOURCE_DIR / "noise.jsonl")
    parser.add_argument("--churn-path", type=Path, default=DEFAULT_SOURCE_DIR / "churn.jsonl")
    parser.add_argument("--bugs-path", type=Path, default=DEFAULT_SOURCE_DIR / "bugs.jsonl")
    parser.add_argument("--features-path", type=Path, default=DEFAULT_SOURCE_DIR / "features.jsonl")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--holdout-path", type=Path, default=DEFAULT_OUT_DIR / "holdout.jsonl")
    args = parser.parse_args()

    if not args.write_jsonl and not args.seed:
        raise SystemExit("Pass --write-jsonl. Postgres runs only with --seed.")

    tenant_id = (args.tenant_id or "").strip()
    bucket_id = (args.bucket_id or "").strip()
    if args.seed and (not tenant_id or not bucket_id):
        raise SystemExit("--seed requires --tenant-id and --bucket-id")

    raw_rows = assemble_raw_rows(
        noise_path=args.noise_path,
        churn_path=args.churn_path,
        bugs_path=args.bugs_path,
        features_path=args.features_path,
    )
    cleaned_rows = apply_feedback_rules(raw_rows)
    _print_summary(cleaned_rows)
    if args.write_jsonl:
        write_corpus_files(
            out_dir=args.out_dir,
            raw_rows=raw_rows,
            cleaned_rows=cleaned_rows,
            holdout_path=args.holdout_path,
        )
        print(f"wrote {args.out_dir}")
    if args.seed:
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


if __name__ == "__main__":
    main()
