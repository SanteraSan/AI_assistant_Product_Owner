from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

import pytest

from app.services.external_db_sync_service import _stable_id
from app.services.sql_schema_card import DEFAULT_SQL_TOOL_ALLOWED_TABLES, build_schema_card


def test_external_tables_are_allowlisted() -> None:
    assert "external_customers" in DEFAULT_SQL_TOOL_ALLOWED_TABLES
    assert "external_support_tickets" in DEFAULT_SQL_TOOL_ALLOWED_TABLES
    card = build_schema_card(allowed_tables=DEFAULT_SQL_TOOL_ALLOWED_TABLES)
    assert "external_customers(" in card
    assert "external_support_tickets(" in card


def test_stable_id_is_deterministic() -> None:
    left = _stable_id("local_demo", "customer", "cust_northwind")
    right = _stable_id("local_demo", "customer", "cust_northwind")
    assert left == right
    assert left == str(
        uuid5(NAMESPACE_URL, "taskflow:local_demo:customer:cust_northwind")
    )


def test_integration_ingest_service_rejects_empty() -> None:
    import asyncio

    from app.services.access_policy import UserContext
    from app.services.integration_ingest_service import IntegrationIngestService

    class _Buckets:
        session_factory = None

    service = IntegrationIngestService(
        bucket_service=_Buckets(),  # type: ignore[arg-type]
        default_bucket_name="n8n Integrations",
    )
    user = UserContext(tenant_id="local_demo", user_id="n8n", roles=frozenset({"admin"}))

    async def _run() -> None:
        await service.ingest_bytes(
            user=user,
            file_name="x.txt",
            content=b"",
            content_type="text/plain",
        )

    with pytest.raises(ValueError, match="empty"):
        asyncio.run(_run())


def test_external_db_sync_response_timestamp_type() -> None:
    # Keep pydantic model importable and typed for API responses.
    from app.models.integrations import ExternalDbSyncResponse

    payload = ExternalDbSyncResponse(
        tenant_id="local_demo",
        customers_upserted=1,
        tickets_upserted=2,
        synced_at=datetime.now(UTC),
    )
    assert payload.status == "ok"
