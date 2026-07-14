from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.sql_execution_service import SqlExecutionService
from app.services.tools.base import ToolContext, ToolResult, tool_failed, tool_invalid, tool_ok


class ExecuteReadonlySqlArgs(BaseModel):
    sql: str = Field(..., min_length=1, max_length=8000)


class ExecuteReadonlySqlTool:
    name = "execute_readonly_sql"
    description = (
        "Validate and execute a read-only SELECT against allowlisted analytics tables. "
        "Returns truncated row results. Requires analyst or admin role. "
        "Prefer generating SQL via text_to_sql first."
    )
    args_model = ExecuteReadonlySqlArgs

    def __init__(self, *, sql_execution_service: SqlExecutionService) -> None:
        self._sql_execution_service = sql_execution_service

    async def run(self, ctx: ToolContext, args: ExecuteReadonlySqlArgs) -> ToolResult:
        del ctx
        try:
            result = await self._sql_execution_service.execute_readonly(args.sql)
        except Exception as exc:  # noqa: BLE001
            return tool_failed(
                error_code="sql_execution_failed",
                error_message=str(exc),
            )

        if result.validation_error:
            return tool_invalid(
                error_code=result.validation_error,
                error_message=f"SQL validation failed: {result.validation_error}",
            )
        if result.execution_error:
            return tool_failed(
                error_code="sql_execution_error",
                error_message=result.execution_error,
            )
        return tool_ok(
            {
                "sql": result.sql,
                "tables": result.tables,
                "row_count": result.row_count,
                "truncated": result.truncated,
                "rows": result.rows,
            }
        )
