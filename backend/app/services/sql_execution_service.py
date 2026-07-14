from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import asyncpg

from app.services.sql_validator import SqlValidationResult, validate_read_only_sql


@dataclass(frozen=True)
class SqlExecutionResult:
    success: bool
    sql: str | None
    tables: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    validation_error: str | None = None
    execution_error: str | None = None


class SqlExecutionService:
    def __init__(
        self,
        *,
        postgres_dsn: str,
        allowed_tables: frozenset[str],
        row_limit: int = 200,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._dsn = _asyncpg_dsn(postgres_dsn)
        self._allowed_tables = allowed_tables
        self._row_limit = row_limit
        self._timeout_seconds = timeout_seconds

    def validate(self, sql: str) -> SqlValidationResult:
        return validate_read_only_sql(sql, allowed_tables=set(self._allowed_tables))

    async def execute_readonly(self, sql: str) -> SqlExecutionResult:
        validation = self.validate(sql)
        if not validation.valid or not validation.normalized_sql:
            return SqlExecutionResult(
                success=False,
                sql=None,
                tables=validation.tables,
                rows=[],
                row_count=0,
                truncated=False,
                validation_error=validation.error,
            )

        limited_sql = _apply_row_limit(validation.normalized_sql, self._row_limit + 1)
        connection = await asyncpg.connect(self._dsn)
        try:
            async with connection.transaction(readonly=True):
                records = await connection.fetch(
                    limited_sql,
                    timeout=self._timeout_seconds,
                )
        except Exception as exc:  # noqa: BLE001 — return structured tool error
            return SqlExecutionResult(
                success=False,
                sql=validation.normalized_sql,
                tables=validation.tables,
                rows=[],
                row_count=0,
                truncated=False,
                execution_error=str(exc),
            )
        finally:
            await connection.close()

        truncated = len(records) > self._row_limit
        records = records[: self._row_limit]
        rows = [dict(record) for record in records]
        return SqlExecutionResult(
            success=True,
            sql=validation.normalized_sql,
            tables=validation.tables,
            rows=_json_safe_rows(rows),
            row_count=len(rows),
            truncated=truncated,
        )


def _asyncpg_dsn(postgres_dsn: str) -> str:
    return postgres_dsn.replace("postgresql+asyncpg://", "postgresql://", 1)


def _apply_row_limit(sql: str, limit: int) -> str:
    # Prefer wrapping so model-produced LIMIT stays inside the subquery.
    return f"SELECT * FROM ({sql}) AS _sql_tool_limited LIMIT {int(limit)}"


def _json_safe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe: list[dict[str, Any]] = []
    for row in rows:
        item: dict[str, Any] = {}
        for key, value in row.items():
            if hasattr(value, "isoformat"):
                item[key] = value.isoformat()
            else:
                item[key] = value
        safe.append(item)
    return safe
