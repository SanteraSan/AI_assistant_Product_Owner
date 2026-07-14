from __future__ import annotations

from sqlalchemy.dialects import postgresql

from app.db.base import Base
from app.db import models as _models  # noqa: F401 — register metadata

# Analytics/domain tables used by text-to-SQL corpus. Excludes ACL / staging internals.
DEFAULT_SQL_TOOL_ALLOWED_TABLES: frozenset[str] = frozenset(
    {
        "bucket_documents",
        "chat_messages",
        "chat_sessions",
        "conversation_summaries",
        "document_assets",
        "document_indexing_jobs",
        "evaluation_results",
        "evaluation_runs",
        "knowledge_buckets",
        "rag_request_logs",
        "rag_source_logs",
        "tool_call_logs",
    }
)


def parse_allowed_tables(raw: str | None) -> frozenset[str]:
    if raw is None or not raw.strip():
        return DEFAULT_SQL_TOOL_ALLOWED_TABLES
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def build_schema_card(*, allowed_tables: frozenset[str]) -> str:
    dialect = postgresql.dialect()
    lines = ["PostgreSQL schema (allowlisted analytics tables only):"]
    for table in sorted(Base.metadata.sorted_tables, key=lambda item: item.name):
        if table.name not in allowed_tables:
            continue
        columns = ", ".join(
            f"{column.name} {column.type.compile(dialect=dialect)}"
            for column in table.columns
        )
        lines.append(f"- {table.name}({columns})")
    return "\n".join(lines)
