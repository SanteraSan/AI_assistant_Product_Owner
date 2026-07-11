from dataclasses import dataclass, field

from app.services.access_policy import UserContext, can_read_document, can_manage_document


@dataclass
class _Document:
    tenant_id: str = "tenant-a"
    owner_user_id: str | None = "owner-a"
    visibility: str = "private"
    allowed_roles: list[str] = field(default_factory=list)


@dataclass
class _AclEntry:
    subject_type: str
    subject_id: str
    permission: str = "read"


def test_owner_can_read_private_document() -> None:
    document = _Document(owner_user_id="user-a")
    user = UserContext(tenant_id="tenant-a", user_id="user-a", roles=frozenset())

    assert can_read_document(document=document, user=user)


def test_private_document_is_hidden_from_other_user() -> None:
    document = _Document(owner_user_id="user-a")
    user = UserContext(tenant_id="tenant-a", user_id="user-b", roles=frozenset())

    assert not can_read_document(document=document, user=user)


def test_admin_can_read_tenant_document() -> None:
    document = _Document(owner_user_id="user-a")
    user = UserContext(tenant_id="tenant-a", user_id="admin-a", roles=frozenset({"admin"}))

    assert can_read_document(document=document, user=user)


def test_role_visibility_requires_role_intersection() -> None:
    document = _Document(
        owner_user_id="user-a",
        visibility="role",
        allowed_roles=["team_lead", "analyst"],
    )
    user = UserContext(tenant_id="tenant-a", user_id="user-b", roles=frozenset({"analyst"}))

    assert can_read_document(document=document, user=user)


def test_acl_admin_grants_manage_permission() -> None:
    document = _Document(owner_user_id="user-a")
    user = UserContext(tenant_id="tenant-a", user_id="user-b", roles=frozenset())
    acl_entries = [_AclEntry(subject_type="user", subject_id="user-b", permission="admin")]

    assert can_manage_document(document=document, user=user, acl_entries=acl_entries)
