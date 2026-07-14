from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from app.core.config import Settings
from app.services.csrf import require_csrf
from app.services.jwt_utils import decode_jwt_payload_unverified
from app.services.oidc import OidcClient, authenticated_user_from_claims
from app.services.security import generate_code_verifier, generate_state
from app.services.session_store import LoginState, SessionStore


def create_auth_router(
    *,
    settings: Settings,
    session_store: SessionStore,
    oidc_client: OidcClient,
) -> APIRouter:
    router = APIRouter(tags=["auth"])

    @router.get("/auth/login")
    async def login(request: Request) -> RedirectResponse:
        state = generate_state()
        code_verifier = generate_code_verifier()
        return_to = _safe_return_to(
            request.query_params.get("return_to"),
            frontend_base_url=settings.frontend_base_url,
        )
        await session_store.save_login_state(
            LoginState(state=state, code_verifier=code_verifier, return_to=return_to)
        )
        return RedirectResponse(
            url=oidc_client.build_authorization_url(state=state, code_verifier=code_verifier),
            status_code=302,
        )

    @router.get("/auth/callback")
    async def callback(request: Request) -> RedirectResponse:
        error = request.query_params.get("error")
        if error:
            raise HTTPException(status_code=400, detail=f"OIDC error: {error}")
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        if not code or not state:
            raise HTTPException(status_code=400, detail="Missing OIDC code or state.")

        login_state = await session_store.pop_login_state(state)
        if login_state is None:
            raise HTTPException(status_code=400, detail="Invalid or expired OIDC state.")

        token_payload = await oidc_client.exchange_code(
            code=code,
            code_verifier=login_state.code_verifier,
        )
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            raise HTTPException(status_code=502, detail="OIDC token response missing access_token.")

        claims = decode_jwt_payload_unverified(access_token)
        user = authenticated_user_from_claims(claims)
        if not user.sub:
            raise HTTPException(status_code=502, detail="OIDC token missing subject.")

        session = await session_store.create_session(
            user=user,
            access_token=access_token,
            refresh_token=(str(token_payload["refresh_token"]) if token_payload.get("refresh_token") else None),
            id_token=(str(token_payload["id_token"]) if token_payload.get("id_token") else None),
        )
        response = RedirectResponse(url=login_state.return_to, status_code=302)
        response.set_cookie(
            key=settings.session_cookie_name,
            value=session.session_id,
            httponly=True,
            secure=settings.cookie_secure,
            samesite=settings.cookie_samesite,
            max_age=settings.session_ttl_seconds,
            path="/",
        )
        return response

    @router.get("/auth/me")
    async def me(request: Request) -> JSONResponse:
        session = await _session_from_request(request, settings=settings, session_store=session_store)
        if session is None:
            raise HTTPException(status_code=401, detail="Not authenticated.")
        return JSONResponse(
            {
                "id": session.user.sub,
                "email": session.user.email,
                "displayName": session.user.name or session.user.email or session.user.sub,
                "tenantId": session.user.tenant_id,
                "roles": session.user.roles,
                "csrfToken": session.csrf_token,
            }
        )

    @router.post("/auth/logout")
    async def logout(request: Request) -> Response:
        session = await _session_from_request(request, settings=settings, session_store=session_store)
        if session is not None:
            require_csrf(request, session_csrf_token=session.csrf_token)
            await session_store.delete_session(session.session_id)
            if session.refresh_token:
                try:
                    await oidc_client.revoke_refresh_token(session.refresh_token)
                except Exception:
                    # Best-effort revoke; local session is already cleared.
                    pass
        response = JSONResponse({"ok": True})
        response.delete_cookie(settings.session_cookie_name, path="/")
        return response

    return router


async def _session_from_request(
    request: Request,
    *,
    settings: Settings,
    session_store: SessionStore,
):
    session_id = request.cookies.get(settings.session_cookie_name)
    if not session_id:
        return None
    return await session_store.get_session(session_id)


def _safe_return_to(value: str | None, *, frontend_base_url: str) -> str:
    fallback = frontend_base_url.rstrip("/") + "/"
    if not value:
        return fallback
    candidate = value.strip()
    if candidate.startswith("/"):
        return frontend_base_url.rstrip("/") + candidate
    parsed = urlparse(candidate)
    allowed = urlparse(frontend_base_url)
    if parsed.scheme == allowed.scheme and parsed.netloc == allowed.netloc:
        return candidate
    return fallback
