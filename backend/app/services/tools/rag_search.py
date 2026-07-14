from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.bucket_service import BucketService
from app.services.rag_scope import resolve_rag_document_ids
from app.services.rag_service import RagService
from app.services.tools.base import ToolContext, ToolResult, tool_ok


class RagSearchArgs(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    bucket_ids: list[str] = Field(default_factory=list, max_length=50)
    document_ids: list[str] = Field(default_factory=list, max_length=50)
    top_k: int | None = Field(default=None, ge=1, le=20)


class RagSearchTool:
    name = "rag_search"
    description = (
        "Search indexed documents the user can access and return evidence chunks "
        "(title, source_type, source_path, score, content excerpt). "
        "Does not generate a final answer — use returned evidence to ground the reply."
    )
    args_model = RagSearchArgs

    def __init__(
        self,
        *,
        bucket_service: BucketService,
        rag_service: RagService,
        content_excerpt_limit: int = 800,
    ) -> None:
        self._bucket_service = bucket_service
        self._rag_service = rag_service
        self._content_excerpt_limit = content_excerpt_limit

    async def run(self, ctx: ToolContext, args: RagSearchArgs) -> ToolResult:
        bucket_documents = []
        for bucket_id in args.bucket_ids:
            cleaned = bucket_id.strip()
            if not cleaned:
                continue
            rows = await self._bucket_service.list_documents(
                user=ctx.user,
                bucket_id=cleaned,
            )
            if rows is None:
                continue
            bucket_documents.extend(document for document, _link in rows)

        scoped_document_ids = await resolve_rag_document_ids(
            user=ctx.user,
            bucket_service=self._bucket_service,
            requested_document_ids=args.document_ids or None,
            bucket_documents=bucket_documents,
        )

        search = await self._rag_service.search(
            query=args.query,
            top_k=args.top_k,
            tenant_id=ctx.user.tenant_id,
            bucket_ids=args.bucket_ids or None,
            document_ids=scoped_document_ids,
        )

        sources = [
            {
                "id": source.id,
                "score": source.score,
                "title": source.title,
                "source_type": source.source_type,
                "source_path": source.source_path,
                "feature": source.feature,
                "content": source.content[: self._content_excerpt_limit],
                "document_id": source.metadata.get("document_id"),
            }
            for source in search.sources
        ]
        return tool_ok(
            {
                "query": args.query,
                "document_ids": scoped_document_ids,
                "bucket_ids": args.bucket_ids,
                "source_count": len(sources),
                "sources": sources,
                "retrieval": search.retrieval,
            }
        )
