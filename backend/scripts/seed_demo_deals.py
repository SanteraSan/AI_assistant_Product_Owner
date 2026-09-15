#!/usr/bin/env python3
"""Upsert synthetic sales buckets and demo_deals into the product Postgres."""

from __future__ import annotations

import argparse
import asyncio
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import DemoDeal, KnowledgeBucket
from app.db.session import create_engine, create_session_factory, init_db
from app.services.sales_demo_data import DEMO_DEAL_SPECS, SALES_BUCKET_SEED


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed sales demo deals into Postgres.")
    parser.add_argument(
        "--tenant-id",
        default=None,
        help="Override tenant id (default: settings.default_tenant_id)",
    )
    args = parser.parse_args()

    settings = get_settings()
    tenant_id = (args.tenant_id or settings.default_tenant_id).strip()
    engine = create_engine(settings.postgres_dsn)
    await init_db(engine)
    session_factory = create_session_factory(engine)

    created_buckets = 0
    updated_deals = 0
    created_deals = 0

    async with session_factory() as session:
        for bucket_id, name, description in SALES_BUCKET_SEED:
            existing = await session.scalar(
                select(KnowledgeBucket).where(
                    KnowledgeBucket.tenant_id == tenant_id,
                    KnowledgeBucket.id == bucket_id,
                )
            )
            if existing is None:
                session.add(
                    KnowledgeBucket(
                        id=bucket_id,
                        tenant_id=tenant_id,
                        name=name,
                        description=description,
                        owner_user_id="system-seed",
                        status="ready",
                        metadata_json={
                            "origin": "seed_demo_deals",
                            "synthetic": True,
                        },
                    )
                )
                created_buckets += 1

        for spec in DEMO_DEAL_SPECS:
            deal_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"demo_deal:{tenant_id}:{spec.bucket_id}:{spec.deal_code}",
                )
            )
            existing_deal = await session.scalar(
                select(DemoDeal).where(
                    DemoDeal.tenant_id == tenant_id,
                    DemoDeal.bucket_id == spec.bucket_id,
                    DemoDeal.deal_code == spec.deal_code,
                )
            )
            payload = {
                "title": spec.title,
                "amount": spec.amount,
                "currency": spec.currency,
                "status": spec.status,
                "close_date": spec.close_date,
                "owner": spec.owner,
                "aliases_json": list(spec.aliases),
            }
            if existing_deal is None:
                session.add(DemoDeal(id=deal_id, tenant_id=tenant_id, bucket_id=spec.bucket_id, deal_code=spec.deal_code, **payload))
                created_deals += 1
            else:
                for key, value in payload.items():
                    setattr(existing_deal, key, value)
                updated_deals += 1

        await session.commit()

    print(f"Tenant: {tenant_id}")
    print(f"Buckets created: {created_buckets}")
    print(f"Deals created: {created_deals}")
    print(f"Deals updated: {updated_deals}")


if __name__ == "__main__":
    asyncio.run(main())
