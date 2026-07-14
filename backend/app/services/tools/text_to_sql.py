from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.text_to_sql_service import TextToSqlService
from app.services.tools.base import ToolContext, ToolResult, tool_failed, tool_invalid, tool_ok


class TextToSqlArgs(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class TextToSqlTool:
    name = "text_to_sql"
    description = (
        "Generate a read-only PostgreSQL SELECT for an analytics question against "
        "the allowlisted schema. Returns SQL + validation status; does not execute. "
        "Requires analyst or admin role."
    )
    args_model = TextToSqlArgs

    def __init__(self, *, text_to_sql_service: TextToSqlService) -> None:
        self._text_to_sql_service = text_to_sql_service

    async def run(self, ctx: ToolContext, args: TextToSqlArgs) -> ToolResult:
        del ctx
        try:
            generation = await self._text_to_sql_service.generate(question=args.question)
        except Exception as exc:  # noqa: BLE001
            return tool_failed(
                error_code="text_to_sql_generation_failed",
                error_message=str(exc),
            )

        payload = {
            "question": generation.question,
            "sql": generation.sql,
            "model_used": generation.model_used,
            "fallback_used": generation.fallback_used,
            "validation_valid": generation.validation_valid,
            "validation_error": generation.validation_error,
            "tables": generation.tables,
            "warning": generation.warning,
        }
        if not generation.validation_valid:
            return tool_invalid(
                error_code=generation.validation_error or "invalid_sql",
                error_message=(
                    f"Generated SQL failed validation: {generation.validation_error}. "
                    f"sql={generation.sql!r}"
                ),
            )
        return tool_ok(payload)
