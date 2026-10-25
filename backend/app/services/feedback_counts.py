from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import FeedbackItem, KnowledgeBucket
from app.services.feedback_index_policy import FEEDBACK_CLASSES, PRODUCT_INDEX_CLASSES


# Response order. The set matches FEEDBACK_CLASSES; indexed uses PRODUCT_INDEX_CLASSES.
_CLASS_ORDER = ("noise", "churn_signal", "bug", "feature")

assert frozenset(_CLASS_ORDER) == FEEDBACK_CLASSES


@dataclass(frozen=True)
class FeedbackCounts:
    noise: int
    churn_signal: int
    bug: int
    feature: int
    total: int
    indexed: int


class FeedbackCountService:
    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def counts_for_bucket(
        self,
        *,
        tenant_id: str,
        bucket_id: str,
    ) -> FeedbackCounts | None:
        """None, если бакета нет в этом tenant. Нули, если бакет есть, а строк нет."""
        async with self._session_factory() as session:
            bucket_row_id = await session.scalar(
                select(KnowledgeBucket.id).where(
                    KnowledgeBucket.tenant_id == tenant_id,
                    KnowledgeBucket.id == bucket_id,
                )
            )
            if bucket_row_id is None:
                return None
            row = (
                await session.execute(
                    _counts_select(tenant_id=tenant_id, bucket_id=bucket_id),
                )
            ).one()

        values = row._mapping
        class_counts = {
            class_name: int(values[class_name] or 0) for class_name in _CLASS_ORDER
        }
        return FeedbackCounts(
            noise=class_counts["noise"],
            churn_signal=class_counts["churn_signal"],
            bug=class_counts["bug"],
            feature=class_counts["feature"],
            total=sum(class_counts[class_name] for class_name in _CLASS_ORDER),
            indexed=int(values["indexed"] or 0),
        )


def _counts_select(*, tenant_id: str, bucket_id: str):
    class_counts = [
        func.count().filter(FeedbackItem.feedback_class == class_name).label(class_name)
        for class_name in _CLASS_ORDER
    ]
    indexed_count = (
        func.count()
        .filter(
            FeedbackItem.index_in_rag.is_(True),
            FeedbackItem.feedback_class.in_(PRODUCT_INDEX_CLASSES),
        )
        .label("indexed")
    )
    return select(*class_counts, indexed_count).where(
        FeedbackItem.tenant_id == tenant_id,
        FeedbackItem.bucket_id == bucket_id,
    )
