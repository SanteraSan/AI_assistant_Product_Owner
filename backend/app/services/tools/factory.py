from __future__ import annotations

from app.services.bucket_service import BucketService
from app.services.rag_service import RagService
from app.services.sql_execution_service import SqlExecutionService
from app.services.text_to_sql_service import TextToSqlService
from app.services.tools.execute_readonly_sql import ExecuteReadonlySqlTool
from app.services.tools.get_document_status import GetDocumentStatusTool
from app.services.tools.get_user_context import GetUserContextTool
from app.services.tools.list_buckets import ListBucketsTool
from app.services.tools.rag_search import RagSearchTool
from app.services.tools.registry import ToolRegistry
from app.services.tools.text_to_sql import TextToSqlTool


def build_default_tool_registry(
    *,
    bucket_service: BucketService,
    rag_service: RagService,
    sql_execution_service: SqlExecutionService | None = None,
    text_to_sql_service: TextToSqlService | None = None,
    sql_tools_enabled: bool = False,
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(GetUserContextTool())
    registry.register(ListBucketsTool(bucket_service=bucket_service))
    registry.register(GetDocumentStatusTool(bucket_service=bucket_service))
    registry.register(
        RagSearchTool(bucket_service=bucket_service, rag_service=rag_service)
    )
    if sql_tools_enabled and sql_execution_service is not None and text_to_sql_service is not None:
        registry.register(TextToSqlTool(text_to_sql_service=text_to_sql_service))
        registry.register(
            ExecuteReadonlySqlTool(sql_execution_service=sql_execution_service)
        )
    return registry
