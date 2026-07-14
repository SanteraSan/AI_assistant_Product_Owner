from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from app.db.models import DocumentAsset
from app.services.bucket_service import BucketService
from app.services.requested_file_scope import find_accessible_document_by_name
from app.services.tools.base import ToolContext, ToolResult, tool_denied, tool_ok


class GetDocumentStatusArgs(BaseModel):
    document_id: str | None = Field(default=None, min_length=1, max_length=36)
    file_name: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def _require_id_or_name(self) -> "GetDocumentStatusArgs":
        document_id = (self.document_id or "").strip() or None
        file_name = (self.file_name or "").strip() or None
        self.document_id = document_id
        self.file_name = file_name
        if document_id is None and file_name is None:
            raise ValueError("Provide document_id or file_name")
        return self


class GetDocumentStatusTool:
    name = "get_document_status"
    description = (
        "Get status and metadata for a document the user can read "
        "(status, file_name, visibility, size_bytes, error). "
        "Pass document_id (UUID) and/or file_name (e.g. moto.jpg, AGENTS.md). "
        "Prefer file_name when the user mentions a file by name — do not ask the user "
        "for UUID if a file name is already known. "
        "Denied when the document is missing or not readable under ACL."
    )
    args_model = GetDocumentStatusArgs

    def __init__(self, *, bucket_service: BucketService) -> None:
        self._bucket_service = bucket_service

    async def run(self, ctx: ToolContext, args: GetDocumentStatusArgs) -> ToolResult:
        if args.document_id:
            document = await self._bucket_service.get_document(
                user=ctx.user,
                document_id=args.document_id,
            )
            if document is None:
                return tool_denied(
                    error_code="document_not_readable",
                    error_message=(
                        "Document not found or not readable for the current user."
                    ),
                )
            return tool_ok(_document_payload(document))

        assert args.file_name is not None
        available = await self._bucket_service.list_available_documents(user=ctx.user)
        document = find_accessible_document_by_name(
            file_name=args.file_name,
            documents=available,
        )
        if document is None:
            return tool_denied(
                error_code="document_not_found_by_name",
                error_message=(
                    f"No accessible document named '{args.file_name}' "
                    "for the current user."
                ),
            )
        return tool_ok(_document_payload(document))


def _document_payload(document: DocumentAsset) -> dict[str, object]:
    return {
        "document_id": document.id,
        "file_name": document.file_name,
        "title": document.title,
        "status": document.status,
        "visibility": document.visibility,
        "source_type": document.source_type,
        "size_bytes": document.size_bytes,
        "error": document.error,
    }
