from __future__ import annotations

import logging
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

from app.core.config import Settings
from app.services.csrf import require_csrf
from app.services.service_jwt import issue_service_jwt
from app.services.session_store import SessionStore

logger = logging.getLogger(__name__)


def create_proxy_router(
    *,
    settings: Settings,
    session_store: SessionStore,
    http_client: httpx.AsyncClient,
) -> APIRouter:
    router = APIRouter(tags=["proxy"])

    @router.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def proxy(path: str, request: Request) -> Response:
        session_id = request.cookies.get(settings.session_cookie_name)
        if not session_id:
            raise HTTPException(status_code=401, detail="Not authenticated.")
        session = await session_store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=401, detail="Not authenticated.")

        require_csrf(request, session_csrf_token=session.csrf_token)

        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        service_token = issue_service_jwt(
            user=session.user,
            secret=settings.service_jwt_secret,
            issuer=settings.service_jwt_issuer,
            audience=settings.service_jwt_audience,
            ttl_seconds=settings.service_jwt_ttl_seconds,
            request_id=request_id,
        )

        backend_url = f"{settings.backend_base_url.rstrip('/')}/{path.lstrip('/')}"
        if request.url.query:
            backend_url = f"{backend_url}?{request.url.query}"

        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower()
            not in {
                "host",
                "content-length",
                "connection",
                "cookie",
                "authorization",
                "x-user-id",
                "x-user-roles",
                "x-tenant-id",
            }
        }
        headers["Authorization"] = f"Bearer {service_token}"
        headers["X-Request-ID"] = request_id

        body = await request.body()
        try:
            upstream = await http_client.request(
                method=request.method,
                url=backend_url,
                headers=headers,
                content=body,
            )
        except httpx.HTTPError as exc:
            logger.exception("Backend proxy failed")
            raise HTTPException(status_code=502, detail="Backend unavailable.") from exc

        excluded = {"content-encoding", "content-length", "transfer-encoding", "connection"}
        response_headers = {
            key: value
            for key, value in upstream.headers.items()
            if key.lower() not in excluded
        }
        response_headers["X-Request-ID"] = request_id
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=response_headers,
            media_type=upstream.headers.get("content-type"),
        )

    return router
