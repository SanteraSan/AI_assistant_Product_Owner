from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt


@dataclass(frozen=True)
class AuthenticatedUser:
    sub: str
    email: str | None
    name: str | None
    roles: list[str]
    tenant_id: str


def issue_service_jwt(
    *,
    user: AuthenticatedUser,
    secret: str,
    issuer: str,
    audience: str,
    ttl_seconds: int,
    request_id: str | None = None,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user.sub,
        "email": user.email,
        "name": user.name,
        "roles": user.roles,
        "tenant_id": user.tenant_id,
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


def user_to_dict(user: AuthenticatedUser) -> dict[str, Any]:
    return asdict(user)


def user_from_dict(payload: dict[str, Any]) -> AuthenticatedUser:
    roles = payload.get("roles") or []
    if not isinstance(roles, list):
        roles = []
    return AuthenticatedUser(
        sub=str(payload.get("sub") or ""),
        email=(str(payload["email"]) if payload.get("email") else None),
        name=(str(payload["name"]) if payload.get("name") else None),
        roles=[str(role) for role in roles if str(role).strip()],
        tenant_id=str(payload.get("tenant_id") or ""),
    )
