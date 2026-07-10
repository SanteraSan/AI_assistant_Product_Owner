from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp


DESTRUCTIVE_SQL_KEYWORDS = {
    "alter",
    "create",
    "delete",
    "drop",
    "grant",
    "insert",
    "merge",
    "revoke",
    "truncate",
    "update",
}


@dataclass(frozen=True)
class SqlValidationResult:
    valid: bool
    normalized_sql: str | None = None
    tables: list[str] = field(default_factory=list)
    error: str | None = None


def extract_sql_from_response(response: str) -> str:
    text = response.strip()
    if "```" not in text:
        return _strip_trailing_semicolon(text)

    parts = text.split("```")
    for index, part in enumerate(parts):
        if index % 2 == 0:
            continue
        candidate = part.strip()
        if candidate.lower().startswith("sql"):
            candidate = candidate[3:].strip()
        if candidate:
            return _strip_trailing_semicolon(candidate)
    return _strip_trailing_semicolon(text)


def validate_read_only_sql(
    sql: str,
    *,
    allowed_tables: set[str] | None = None,
) -> SqlValidationResult:
    candidate = _strip_trailing_semicolon(sql.strip())
    if not candidate:
        return SqlValidationResult(valid=False, error="empty_sql")

    lowered_tokens = {
        token.lower()
        for token in candidate.replace("(", " ").replace(")", " ").replace(";", " ").split()
    }
    destructive = sorted(lowered_tokens & DESTRUCTIVE_SQL_KEYWORDS)
    if destructive:
        return SqlValidationResult(
            valid=False,
            error=f"destructive_keyword:{','.join(destructive)}",
        )

    try:
        statements = sqlglot.parse(candidate, read="postgres")
    except sqlglot.errors.ParseError as exc:
        return SqlValidationResult(valid=False, error=f"parse_error:{exc}")

    if len(statements) != 1:
        return SqlValidationResult(valid=False, error="multiple_statements")

    statement = statements[0]
    if not isinstance(statement, exp.Select):
        return SqlValidationResult(valid=False, error="not_select")

    cte_names = {cte.alias_or_name for cte in statement.find_all(exp.CTE)}
    tables = sorted(
        {
            table.name
            for table in statement.find_all(exp.Table)
            if table.name not in cte_names
        }
    )
    if allowed_tables is not None:
        unknown_tables = sorted(set(tables) - allowed_tables)
        if unknown_tables:
            return SqlValidationResult(
                valid=False,
                tables=tables,
                error=f"unknown_tables:{','.join(unknown_tables)}",
            )

    return SqlValidationResult(
        valid=True,
        normalized_sql=statement.sql(dialect="postgres"),
        tables=tables,
    )


def _strip_trailing_semicolon(sql: str) -> str:
    return sql.strip().removesuffix(";").strip()
