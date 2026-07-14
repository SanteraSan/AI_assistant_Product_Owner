from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app import main as main_module
from app.core.config import get_settings
from app.services.access_policy import UserContext
from app.services.rag_scope import resolve_rag_document_ids
from app.services.service_jwt import (
    decode_service_jwt,
    issue_service_jwt,
    user_context_from_claims,
)
from tests.auth_helpers import auth_headers


def test_service_jwt_roundtrip_maps_to_user_context() -> None:
    settings = get_settings()
    token = issue_service_jwt(
        sub="user-1",
        tenant_id="local_demo",
        roles=["analyst", "viewer"],
        secret=settings.service_jwt_secret,
        issuer=settings.service_jwt_issuer,
        audience=settings.service_jwt_audience,
        email="analyst@local",
    )
    claims = decode_service_jwt(
        token,
        secret=settings.service_jwt_secret,
        issuer=settings.service_jwt_issuer,
        audience=settings.service_jwt_audience,
    )
    user = user_context_from_claims(claims)
    assert user.user_id == "user-1"
    assert user.tenant_id == "local_demo"
    assert user.roles == frozenset({"analyst", "viewer"})


def test_protected_endpoint_rejects_missing_and_spoofed_headers() -> None:
    client = TestClient(main_module.app)

    missing = client.get("/chat/sessions")
    assert missing.status_code == 401

    spoofed = client.get(
        "/chat/sessions",
        headers={
            "X-Tenant-ID": "local_demo",
            "X-User-ID": "attacker",
            "X-User-Roles": "admin",
        },
    )
    assert spoofed.status_code == 401


def test_protected_endpoint_accepts_valid_service_jwt() -> None:
    client = TestClient(main_module.app)
    response = client.get("/chat/sessions", headers=auth_headers(roles=["viewer"]))
    # Identity must pass; DB availability may still yield 5xx in local smoke.
    assert response.status_code != 401


def test_resolve_rag_document_ids_drops_unauthorized() -> None:
    class _Doc:
        def __init__(self, document_id: str, status: str = "indexed") -> None:
            self.id = document_id
            self.status = status

    class _BucketService:
        async def get_document(self, *, user: UserContext, document_id: str):
            if document_id == "allowed-doc":
                return _Doc("allowed-doc")
            return None

        async def list_available_documents(self, *, user: UserContext):
            return [_Doc("available-doc")]

    async def _run() -> None:
        user = UserContext(tenant_id="local_demo", user_id="u1", roles=frozenset({"viewer"}))
        allowed = await resolve_rag_document_ids(
            user=user,
            bucket_service=_BucketService(),  # type: ignore[arg-type]
            requested_document_ids=["allowed-doc", "secret-doc"],
            bucket_documents=[],
        )
        assert allowed == ["allowed-doc"]

        fallback = await resolve_rag_document_ids(
            user=user,
            bucket_service=_BucketService(),  # type: ignore[arg-type]
            requested_document_ids=None,
            bucket_documents=[],
        )
        assert fallback == ["available-doc"]

    asyncio.run(_run())
