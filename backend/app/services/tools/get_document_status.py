from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.bucket_service import BucketService
from app.services.tools.base import ToolContext, ToolResult, tool_denied, tool_ok


class GetDocumentStatusArgs(BaseModel):
    document_id: str = Field(..., min_length=1, max_length=36)


class GetDocumentStatusTool:
    name = "get_document_status"
    description = (
        "Get status and metadata for a document the user can read "
        "(status, file_name, visibility, size_bytes, error). "
        "Denied when the document is missing or not readable under ACL."
    )
    args_model = GetDocumentStatusArgs

    def __init__(self, *, bucket_service: BucketService) -> None:
        self._bucket_service = bucket_service

    async def run(self, ctx: ToolContext, args: GetDocumentStatusArgs) -> ToolResult:
        document = await self._bucket_service.get_document(
            user=ctx.user,
            document_id=args.document_id.strip(),
        )
        if document is None:
            return tool_denied(
                error_code="document_not_readable",
                error_message=(
                    "Document not found or not readable for the current user."
                ),
            )
        return tool_ok(
            {
                "document_id": document.id,
                "file_name": document.file_name,
                "title": document.title,
                "status": document.status,
                "visibility": document.visibility,
                "source_type": document.source_type,
                "size_bytes": document.size_bytes,
                "error": document.error,
            }
        )
