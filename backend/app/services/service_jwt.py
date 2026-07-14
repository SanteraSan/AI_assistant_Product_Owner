from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt

from app.services.access_policy import UserContext


def issue_service_jwt(
    *,
    sub: str,
    tenant_id: str,
    roles: list[str],
    secret: str,
    issuer: str,
    audience: str,
    ttl_seconds: int = 60,
    email: str | None = None,
    name: str | None = None,
    request_id: str | None = None,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": sub,
        "email": email,
        "name": name,
        "roles": roles,
        "tenant_id": tenant_id,
        "request_id": request_id or str(uuid4()),
        "iss": issuer,
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_service_jwt(
    token: str,
    *,
    secret: str,
    issuer: str,
    audience: str,
) -> dict[str, Any]:
    return jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        audience=audience,
        issuer=issuer,
    )


def user_context_from_claims(claims: dict[str, Any]) -> UserContext:
    roles = claims.get("roles") or []
    if not isinstance(roles, list):
        roles = []
    tenant_id = str(claims.get("tenant_id") or "").strip()
    sub = str(claims.get("sub") or "").strip()
    if not tenant_id:
        raise ValueError("service JWT missing tenant_id")
    if not sub:
        raise ValueError("service JWT missing sub")
    return UserContext(
        tenant_id=tenant_id,
        user_id=sub,
        roles=frozenset(str(role) for role in roles if str(role).strip()),
    )
