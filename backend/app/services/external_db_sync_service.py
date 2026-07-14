"""Sync a slice from synthetic external Postgres into allowlisted external_* tables."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import ExternalCustomer, ExternalSupportTicket


class ExternalDbSyncService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        external_postgres_dsn: str,
    ) -> None:
        self._session_factory = session_factory
        self._external_postgres_dsn = external_postgres_dsn

    async def sync_tenant(self, *, tenant_id: str) -> dict[str, object]:
        synced_at = datetime.now(UTC)
        external_engine = create_async_engine(self._external_postgres_dsn, pool_pre_ping=True)
        try:
            async with external_engine.connect() as conn:
                customer_rows = (
                    await conn.execute(
                        text(
                            """
                            SELECT external_id, name, segment, arr_usd
                            FROM demo_customers
                            ORDER BY external_id
                            """
                        )
                    )
                ).mappings().all()
                ticket_rows = (
                    await conn.execute(
                        text(
                            """
                            SELECT
                                external_id,
                                customer_external_id,
                                subject,
                                status,
                                priority,
                                product_area
                            FROM demo_support_tickets
                            ORDER BY external_id
                            """
                        )
                    )
                ).mappings().all()
        finally:
            await external_engine.dispose()

        async with self._session_factory() as session:
            for row in customer_rows:
                external_id = str(row["external_id"])
                existing = await session.get(
                    ExternalCustomer,
                    _stable_id(tenant_id, "customer", external_id),
                )
                if existing is None:
                    session.add(
                        ExternalCustomer(
                            id=_stable_id(tenant_id, "customer", external_id),
                            tenant_id=tenant_id,
                            external_id=external_id,
                            name=str(row["name"]),
                            segment=str(row["segment"]),
                            arr_usd=int(row["arr_usd"] or 0),
                            synced_at=synced_at,
                        )
                    )
                else:
                    existing.name = str(row["name"])
                    existing.segment = str(row["segment"])
                    existing.arr_usd = int(row["arr_usd"] or 0)
                    existing.synced_at = synced_at

            for row in ticket_rows:
                external_id = str(row["external_id"])
                existing = await session.get(
                    ExternalSupportTicket,
                    _stable_id(tenant_id, "ticket", external_id),
                )
                if existing is None:
                    session.add(
                        ExternalSupportTicket(
                            id=_stable_id(tenant_id, "ticket", external_id),
                            tenant_id=tenant_id,
                            external_id=external_id,
                            customer_external_id=str(row["customer_external_id"]),
                            subject=str(row["subject"]),
                            status=str(row["status"]),
                            priority=str(row["priority"]),
                            product_area=str(row["product_area"]),
                            synced_at=synced_at,
                        )
                    )
                else:
                    existing.customer_external_id = str(row["customer_external_id"])
                    existing.subject = str(row["subject"])
                    existing.status = str(row["status"])
                    existing.priority = str(row["priority"])
                    existing.product_area = str(row["product_area"])
                    existing.synced_at = synced_at

            await session.commit()

        return {
            "tenant_id": tenant_id,
            "customers_upserted": len(customer_rows),
            "tickets_upserted": len(ticket_rows),
            "status": "ok",
            "synced_at": synced_at,
        }


def _stable_id(tenant_id: str, kind: str, external_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"taskflow:{tenant_id}:{kind}:{external_id}"))
