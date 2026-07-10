from app.services.sql_validator import extract_sql_from_response, validate_read_only_sql


def test_extract_sql_from_markdown_fence() -> None:
    response = """Вот SQL:

```sql
SELECT * FROM evaluation_runs;
```
"""

    assert extract_sql_from_response(response) == "SELECT * FROM evaluation_runs"


def test_validate_read_only_sql_accepts_select_with_allowed_tables() -> None:
    result = validate_read_only_sql(
        "SELECT id, status FROM evaluation_runs",
        allowed_tables={"evaluation_runs"},
    )

    assert result.valid is True
    assert result.tables == ["evaluation_runs"]
    assert result.normalized_sql is not None


def test_validate_read_only_sql_accepts_cte() -> None:
    result = validate_read_only_sql(
        """
        WITH latest_runs AS (
            SELECT id FROM evaluation_runs
        )
        SELECT count(*) FROM latest_runs
        """,
        allowed_tables={"evaluation_runs"},
    )

    assert result.valid is True


def test_validate_read_only_sql_rejects_destructive_keyword() -> None:
    result = validate_read_only_sql("DELETE FROM evaluation_runs")

    assert result.valid is False
    assert result.error == "destructive_keyword:delete"


def test_validate_read_only_sql_rejects_multiple_statements() -> None:
    result = validate_read_only_sql("SELECT 1; SELECT 2")

    assert result.valid is False
    assert result.error == "multiple_statements"


def test_validate_read_only_sql_rejects_unknown_tables() -> None:
    result = validate_read_only_sql(
        "SELECT * FROM billing_events",
        allowed_tables={"evaluation_runs"},
    )

    assert result.valid is False
    assert result.error == "unknown_tables:billing_events"
