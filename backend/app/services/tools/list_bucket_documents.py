from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.bucket_service import BucketService
from app.services.tools.base import ToolContext, ToolResult, tool_denied, tool_invalid, tool_ok


class ListBucketDocumentsArgs(BaseModel):
    bucket_id: str | None = Field(
        default=None,
        max_length=36,
        description="Knowledge bucket id. If omitted, uses UI active_bucket_id / bucket_ids scope.",
    )
    limit: int = Field(default=50, ge=1, le=200)


class ListBucketDocumentsTool:
    name = "list_bucket_documents"
    description = (
        "List files/documents inside one knowledge bucket the user can read "
        "(file_name, status, source_type, document_id). "
        "Use this when the user asks which files are in a bucket — NOT list_buckets. "
        "If bucket_id is omitted, uses the UI-selected bucket from session scope."
    )
    args_model = ListBucketDocumentsArgs

    def __init__(self, *, bucket_service: BucketService) -> None:
        self._bucket_service = bucket_service

    async def run(self, ctx: ToolContext, args: ListBucketDocumentsArgs) -> ToolResult:
        bucket_id = (args.bucket_id or "").strip() or _scope_bucket_id(ctx.extras)
        if not bucket_id:
            return tool_invalid(
                error_code="bucket_id_required",
                error_message=(
                    "bucket_id is required when no UI active bucket is in scope. "
                    "Call list_buckets first, then retry with a bucket_id."
                ),
            )

        rows = await self._bucket_service.list_documents(
            user=ctx.user,
            bucket_id=bucket_id,
        )
        if rows is None:
            return tool_denied(
                error_code="bucket_not_found",
                error_message=f"Bucket '{bucket_id}' not found in tenant.",
            )

        documents = []
        for document, link in rows[: args.limit]:
            documents.append(
                {
                    "document_id": document.id,
                    "file_name": document.file_name,
                    "title": document.title,
                    "status": document.status,
                    "source_type": document.source_type,
                    "visibility": document.visibility,
                    "indexing_status": link.indexing_status,
                    "size_bytes": document.size_bytes,
                }
            )
        return tool_ok(
            {
                "bucket_id": bucket_id,
                "document_count": len(documents),
                "truncated": len(rows) > args.limit,
                "documents": documents,
            }
        )


def _scope_bucket_id(extras: dict) -> str | None:
    active = extras.get("active_bucket_id")
    if isinstance(active, str) and active.strip():
        return active.strip()
    bucket_ids = extras.get("bucket_ids")
    if isinstance(bucket_ids, list):
        for item in bucket_ids:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return None
