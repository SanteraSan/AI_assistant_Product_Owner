from __future__ import annotations

from pydantic import BaseModel

from app.services.bucket_service import BucketService
from app.services.tools.base import ToolContext, ToolResult, tool_ok


class ListBucketsArgs(BaseModel):
    """No parameters — lists buckets in the user's tenant."""


class ListBucketsTool:
    name = "list_buckets"
    description = (
        "List knowledge buckets available in the current tenant "
        "(id, name, description, document_count). Tenant-scoped; "
        "bucket-level RBAC is not applied yet."
    )
    args_model = ListBucketsArgs

    def __init__(self, *, bucket_service: BucketService) -> None:
        self._bucket_service = bucket_service

    async def run(self, ctx: ToolContext, args: ListBucketsArgs) -> ToolResult:
        del args
        rows = await self._bucket_service.list_buckets(tenant_id=ctx.user.tenant_id)
        buckets = [
            {
                "id": bucket.id,
                "name": bucket.name,
                "description": bucket.description,
                "document_count": document_count,
                "status": bucket.status,
            }
            for bucket, document_count in rows
        ]
        return tool_ok({"tenant_id": ctx.user.tenant_id, "buckets": buckets})
