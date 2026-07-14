from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.access_policy import UserContext
from app.services.tools.base import ToolContext
from app.services.tools.list_bucket_documents import ListBucketDocumentsTool
from app.services.tools.list_bucket_documents import ListBucketDocumentsArgs
from app.services.tools.permissions import can_invoke_tool


def _user(*roles: str) -> UserContext:
    return UserContext(tenant_id="t1", user_id="u1", roles=frozenset(roles))


@pytest.mark.anyio
async def test_list_bucket_documents_uses_active_bucket_from_scope() -> None:
    document = SimpleNamespace(
        id="doc-1",
        file_name="moto.jpg",
        title="moto.jpg",
        status="indexed",
        source_type="jpg",
        visibility="private",
        size_bytes=12,
    )
    link = SimpleNamespace(indexing_status="indexed")

    class _Buckets:
        async def list_documents(self, *, user, bucket_id):
            assert bucket_id == "bucket-ui"
            return [(document, link)]

    tool = ListBucketDocumentsTool(bucket_service=_Buckets())  # type: ignore[arg-type]
    ctx = ToolContext(
        user=_user("viewer"),
        request_id="req-1",
        extras={"active_bucket_id": "bucket-ui"},
    )
    result = await tool.run(ctx, ListBucketDocumentsArgs())
    assert result.ok
    assert result.data["bucket_id"] == "bucket-ui"
    assert result.data["documents"][0]["file_name"] == "moto.jpg"


def test_new_agent_tools_are_allowed_for_viewer() -> None:
    roles = frozenset({"viewer"})
    assert can_invoke_tool(tool_name="list_bucket_documents", roles=roles)
    assert can_invoke_tool(tool_name="analyze_image", roles=roles)
