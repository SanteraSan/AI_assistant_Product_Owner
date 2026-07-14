from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.tools.base import ToolContext, ToolResult, tool_ok


class GetUserContextArgs(BaseModel):
    """No parameters — returns the authenticated user context."""


class GetUserContextTool:
    name = "get_user_context"
    description = (
        "Return the current authenticated user context: user_id, tenant_id, roles, "
        "and is_admin. Use for questions about the user's identity, tenant, or permissions."
    )
    args_model = GetUserContextArgs

    async def run(self, ctx: ToolContext, args: GetUserContextArgs) -> ToolResult:
        del args
        user = ctx.user
        return tool_ok(
            {
                "user_id": user.user_id,
                "tenant_id": user.tenant_id,
                "roles": sorted(user.roles),
                "is_admin": user.is_admin,
            }
        )
