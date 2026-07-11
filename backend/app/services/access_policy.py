from dataclasses import dataclass
from typing import Protocol


ADMIN_ROLES = {"admin"}
READ_PERMISSIONS = {"read", "write", "admin"}
MANAGE_PERMISSIONS = {"write", "admin"}


@dataclass(frozen=True)
class UserContext:
    tenant_id: str
    user_id: str | None
    roles: frozenset[str]

    @property
    def is_admin(self) -> bool:
        return bool(self.roles.intersection(ADMIN_ROLES))


class DocumentLike(Protocol):
    tenant_id: str
    owner_user_id: str | None
    visibility: str
    allowed_roles: list[str]


class AclEntryLike(Protocol):
    subject_type: str
    subject_id: str
    permission: str


def can_read_document(
    *,
    document: DocumentLike,
    user: UserContext,
    acl_entries: list[AclEntryLike] | None = None,
) -> bool:
    if document.tenant_id != user.tenant_id:
        return False
    if user.is_admin:
        return True
    if user.user_id and document.owner_user_id == user.user_id:
        return True
    if document.visibility == "tenant":
        return True
    if document.visibility == "role" and set(document.allowed_roles).intersection(user.roles):
        return True
    return _has_acl_permission(
        acl_entries=acl_entries or [],
        user=user,
        allowed_permissions=READ_PERMISSIONS,
    )


def can_manage_document(
    *,
    document: DocumentLike,
    user: UserContext,
    acl_entries: list[AclEntryLike] | None = None,
) -> bool:
    if document.tenant_id != user.tenant_id:
        return False
    if user.is_admin:
        return True
    if user.user_id and document.owner_user_id == user.user_id:
        return True
    return _has_acl_permission(
        acl_entries=acl_entries or [],
        user=user,
        allowed_permissions=MANAGE_PERMISSIONS,
    )


def parse_roles(raw_roles: str | None) -> frozenset[str]:
    return frozenset(role.strip() for role in (raw_roles or "").split(",") if role.strip())


def _has_acl_permission(
    *,
    acl_entries: list[AclEntryLike],
    user: UserContext,
    allowed_permissions: set[str],
) -> bool:
    for entry in acl_entries:
        if entry.permission not in allowed_permissions:
            continue
        if entry.subject_type == "user" and user.user_id and entry.subject_id == user.user_id:
            return True
        if entry.subject_type == "role" and entry.subject_id in user.roles:
            return True
    return False
