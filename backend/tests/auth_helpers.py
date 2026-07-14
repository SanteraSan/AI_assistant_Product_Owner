from __future__ import annotations

from app.core.config import get_settings
from app.services.service_jwt import issue_service_jwt


def auth_headers(
    *,
    sub: str = "local-user-1",
    tenant_id: str = "local_demo",
    roles: list[str] | None = None,
    email: str | None = None,
) -> dict[str, str]:
    settings = get_settings()
    token = issue_service_jwt(
        sub=sub,
        tenant_id=tenant_id,
        roles=roles or ["admin"],
        secret=settings.service_jwt_secret,
        issuer=settings.service_jwt_issuer,
        audience=settings.service_jwt_audience,
        email=email,
    )
    return {"Authorization": f"Bearer {token}"}
