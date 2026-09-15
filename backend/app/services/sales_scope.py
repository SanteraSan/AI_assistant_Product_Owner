from __future__ import annotations

from collections.abc import Sequence

SALES_NORTHWIND_BUCKET_ID = "sales_northwind"
SALES_AURORA_BUCKET_ID = "sales_aurora"
SALES_BUCKET_IDS: frozenset[str] = frozenset(
    {SALES_NORTHWIND_BUCKET_ID, SALES_AURORA_BUCKET_ID}
)
SALES_RETRIEVAL_FEATURES = ["sales"]
SALES_RETRIEVAL_SOURCE_TYPES = [
    "sales_contract",
    "sales_email",
    "sales_playbook",
    "sales_note",
    "markdown",
    "md",
]


def is_sales_rag_scope(bucket_ids: Sequence[str] | None) -> bool:
    """Composer only when every selected bucket is a sales demo cabinet."""
    selected = [item.strip() for item in (bucket_ids or []) if item and item.strip()]
    if not selected:
        return False
    return all(bucket_id in SALES_BUCKET_IDS for bucket_id in selected)
