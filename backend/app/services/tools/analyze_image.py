from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel, Field, model_validator

from app.db.models import DocumentAsset
from app.services.bucket_service import BucketService
from app.services.image_digest_service import build_targeted_image_digest
from app.services.object_storage import ObjectStorage, display_name_from_ref
from app.services.ollama_client import OllamaClient
from app.services.requested_file_scope import find_accessible_document_by_name
from app.services.tools.base import (
    ToolContext,
    ToolResult,
    tool_denied,
    tool_failed,
    tool_invalid,
    tool_ok,
)

IMAGE_SOURCE_TYPES = {"png", "jpg", "jpeg", "webp", "gif"}


class AnalyzeImageArgs(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    document_id: str | None = Field(default=None, min_length=1, max_length=36)
    file_name: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def _require_id_or_name(self) -> "AnalyzeImageArgs":
        document_id = (self.document_id or "").strip() or None
        file_name = (self.file_name or "").strip() or None
        self.document_id = document_id
        self.file_name = file_name
        return self


class AnalyzeImageTool:
    name = "analyze_image"
    description = (
        "Visually analyze an image document the user can read (PNG/JPEG/…). "
        "Use for questions like what is in the picture / color / objects on the image. "
        "Pass file_name (preferred) or document_id. "
        "If omitted and UI scope has exactly one image document_id, that file is used. "
        "Returns a targeted vision digest as evidence — do not invent visual details."
    )
    args_model = AnalyzeImageArgs

    def __init__(
        self,
        *,
        bucket_service: BucketService,
        ollama_client: OllamaClient,
        object_storage: ObjectStorage,
        vision_model: str,
        vision_enabled: bool = True,
    ) -> None:
        self._bucket_service = bucket_service
        self._ollama_client = ollama_client
        self._object_storage = object_storage
        self._vision_model = vision_model
        self._vision_enabled = vision_enabled

    async def run(self, ctx: ToolContext, args: AnalyzeImageArgs) -> ToolResult:
        if not self._vision_enabled:
            return tool_failed(
                error_code="vision_disabled",
                error_message="Image vision is disabled on this server.",
            )

        document = await self._resolve_document(ctx=ctx, args=args)
        if document is None:
            return tool_denied(
                error_code="image_document_not_found",
                error_message=(
                    "No accessible image document matched. "
                    "Pass file_name/document_id or attach/select an image in the UI."
                ),
            )
        if (document.source_type or "").lower() not in IMAGE_SOURCE_TYPES:
            return tool_invalid(
                error_code="not_an_image",
                error_message=(
                    f"Document '{document.file_name}' source_type="
                    f"'{document.source_type}' is not an image."
                ),
            )
        if not document.source_path or not self._object_storage.exists(document.source_path):
            return tool_failed(
                error_code="image_file_missing",
                error_message=f"Image file for '{document.file_name}' is not available in storage.",
            )

        try:
            with TemporaryDirectory(prefix="agent-vision-") as temporary_dir_name:
                temporary_path = (
                    Path(temporary_dir_name) / display_name_from_ref(document.source_path)
                )
                self._object_storage.materialize(document.source_path, temporary_path)
                digest = await build_targeted_image_digest(
                    temporary_path,
                    question=args.question,
                    ollama_client=self._ollama_client,
                    vision_model=self._vision_model,
                )
        except Exception as exc:  # noqa: BLE001
            return tool_failed(
                error_code="vision_failed",
                error_message=str(exc),
            )

        content = str(digest.get("content") or "").strip()
        if not content:
            return tool_failed(
                error_code="empty_vision_digest",
                error_message="Vision model returned an empty description.",
            )

        return tool_ok(
            {
                "document_id": document.id,
                "file_name": document.file_name,
                "source_type": document.source_type,
                "source_path": document.source_path,
                "vision_model": self._vision_model,
                "question": args.question.strip(),
                "digest": content,
                "image_width": digest.get("image_width"),
                "image_height": digest.get("image_height"),
                "image_format": digest.get("image_format"),
                "sources": [
                    {
                        "id": f"vision:{document.id}",
                        "title": f"{document.file_name} - targeted image analysis",
                        "source_type": "image_targeted_digest",
                        "source_path": document.source_path,
                        "score": None,
                    }
                ],
            }
        )

    async def _resolve_document(
        self,
        *,
        ctx: ToolContext,
        args: AnalyzeImageArgs,
    ) -> DocumentAsset | None:
        if args.document_id:
            return await self._bucket_service.get_document(
                user=ctx.user,
                document_id=args.document_id,
            )
        if args.file_name:
            available = await self._bucket_service.list_available_documents(user=ctx.user)
            return find_accessible_document_by_name(
                file_name=args.file_name,
                documents=available,
            )

        scoped_ids = [
            item.strip()
            for item in (ctx.extras.get("document_ids") or [])
            if isinstance(item, str) and item.strip()
        ]
        if len(scoped_ids) == 1:
            return await self._bucket_service.get_document(
                user=ctx.user,
                document_id=scoped_ids[0],
            )
        if scoped_ids:
            # Prefer first readable image among scoped docs.
            for document_id in scoped_ids:
                document = await self._bucket_service.get_document(
                    user=ctx.user,
                    document_id=document_id,
                )
                if document is not None and (document.source_type or "").lower() in IMAGE_SOURCE_TYPES:
                    return document
        return None
