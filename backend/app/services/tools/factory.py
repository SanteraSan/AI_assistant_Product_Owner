from __future__ import annotations

from app.services.bucket_service import BucketService
from app.services.rag_service import RagService
from app.services.tools.get_document_status import GetDocumentStatusTool
from app.services.tools.get_user_context import GetUserContextTool
from app.services.tools.list_buckets import ListBucketsTool
from app.services.tools.rag_search import RagSearchTool
from app.services.tools.registry import ToolRegistry


def build_default_tool_registry(
    *,
    bucket_service: BucketService,
    rag_service: RagService,
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(GetUserContextTool())
    registry.register(ListBucketsTool(bucket_service=bucket_service))
    registry.register(GetDocumentStatusTool(bucket_service=bucket_service))
    registry.register(
        RagSearchTool(bucket_service=bucket_service, rag_service=rag_service)
    )
    return registry
