from __future__ import annotations

from dataclasses import dataclass

from app.services.access_policy import ADMIN_ROLES


@dataclass(frozen=True)
class ToolPermission:
    """Role gate before tool execution.

    - any_authenticated=True: any signed-in user (viewer/analyst/admin/custom)
    - roles: explicit allowlist (admin always included when listed in matrix)
    """

    any_authenticated: bool = False
    roles: frozenset[str] = frozenset()


# Explicit matrix from E3 plan. SQL tools registered in E3.2.
TOOL_PERMISSIONS: dict[str, ToolPermission] = {
    "get_user_context": ToolPermission(any_authenticated=True),
    "list_buckets": ToolPermission(any_authenticated=True),
    "get_document_status": ToolPermission(any_authenticated=True),
    "rag_search": ToolPermission(any_authenticated=True),
    "text_to_sql": ToolPermission(roles=frozenset({"analyst", "admin"})),
    "execute_readonly_sql": ToolPermission(roles=frozenset({"analyst", "admin"})),
}


def can_invoke_tool(*, tool_name: str, roles: frozenset[str]) -> bool:
    permission = TOOL_PERMISSIONS.get(tool_name)
    if permission is None:
        return False
    if permission.any_authenticated:
        return True
    if roles.intersection(ADMIN_ROLES):
        return True
    return bool(roles.intersection(permission.roles))


def required_roles_for(tool_name: str) -> frozenset[str] | None:
    permission = TOOL_PERMISSIONS.get(tool_name)
    if permission is None:
        return None
    if permission.any_authenticated:
        return None
    return permission.roles
