from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import DemoDeal
from app.services.sales_deal_code import DealIdentity


@dataclass(frozen=True)
class DemoDealRecord:
    tenant_id: str
    bucket_id: str
    deal_code: str
    title: str
    amount: int
    currency: str
    status: str
    close_date: date
    owner: str
    aliases: tuple[str, ...] = ()

    def identity(self) -> DealIdentity:
        return DealIdentity(
            deal_code=self.deal_code,
            bucket_id=self.bucket_id,
            title=self.title,
            aliases=self.aliases,
        )


class DealCardRepository(Protocol):
    async def list_identities(
        self,
        *,
        tenant_id: str,
        bucket_ids: list[str],
    ) -> list[DealIdentity]: ...

    async def get_card(
        self,
        *,
        tenant_id: str,
        bucket_ids: list[str],
        deal_code: str,
    ) -> DemoDealRecord | None: ...


class PostgresDealCardRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_identities(
        self,
        *,
        tenant_id: str,
        bucket_ids: list[str],
    ) -> list[DealIdentity]:
        if not bucket_ids:
            return []
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(DemoDeal).where(
                    DemoDeal.tenant_id == tenant_id,
                    DemoDeal.bucket_id.in_(bucket_ids),
                )
            )
            return [_to_record(row).identity() for row in rows]

    async def get_card(
        self,
        *,
        tenant_id: str,
        bucket_ids: list[str],
        deal_code: str,
    ) -> DemoDealRecord | None:
        if not bucket_ids or not deal_code:
            return None
        async with self._session_factory() as session:
            row = await session.scalar(
                select(DemoDeal).where(
                    DemoDeal.tenant_id == tenant_id,
                    DemoDeal.bucket_id.in_(bucket_ids),
                    DemoDeal.deal_code == deal_code,
                )
            )
            return _to_record(row) if row is not None else None


def _to_record(row: DemoDeal) -> DemoDealRecord:
    aliases = row.aliases_json if isinstance(row.aliases_json, list) else []
    return DemoDealRecord(
        tenant_id=row.tenant_id,
        bucket_id=row.bucket_id,
        deal_code=row.deal_code,
        title=row.title,
        amount=row.amount,
        currency=row.currency,
        status=row.status,
        close_date=row.close_date,
        owner=row.owner,
        aliases=tuple(str(item) for item in aliases if str(item).strip()),
    )
