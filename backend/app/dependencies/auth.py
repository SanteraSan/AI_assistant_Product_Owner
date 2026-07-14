from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.services.access_policy import UserContext
from app.services.service_jwt import decode_service_jwt, user_context_from_claims

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> UserContext:
    """Resolve identity only from signed BFF service JWT.

    Browser X-User-* / X-Tenant-ID headers are intentionally ignored.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing bearer service token.")
    try:
        claims = decode_service_jwt(
            credentials.credentials,
            secret=settings.service_jwt_secret,
            issuer=settings.service_jwt_issuer,
            audience=settings.service_jwt_audience,
        )
        return user_context_from_claims(claims)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired service token.") from exc


def require_user_id(user: UserContext) -> str:
    if not user.user_id:
        raise HTTPException(status_code=401, detail="Authenticated user id is required.")
    return user.user_id
