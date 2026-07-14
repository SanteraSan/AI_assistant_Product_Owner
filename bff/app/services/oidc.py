from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import Settings
from app.services.security import code_challenge_s256
from app.services.service_jwt import AuthenticatedUser


class OidcClient:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http_client

    def build_authorization_url(
        self,
        *,
        state: str,
        code_verifier: str,
        prompt: str | None = None,
    ) -> str:
        params: dict[str, str] = {
            "client_id": self._settings.keycloak_client_id,
            "response_type": "code",
            "scope": "openid profile email",
            "redirect_uri": self._settings.callback_url,
            "state": state,
            "code_challenge": code_challenge_s256(code_verifier),
            "code_challenge_method": "S256",
        }
        if prompt:
            params["prompt"] = prompt
        return f"{self._settings.authorization_endpoint}?{urlencode(params)}"

    def build_end_session_url(
        self,
        *,
        id_token: str | None,
        post_logout_redirect_uri: str,
    ) -> str:
        params: dict[str, str] = {
            "client_id": self._settings.keycloak_client_id,
            "post_logout_redirect_uri": post_logout_redirect_uri,
        }
        if id_token:
            params["id_token_hint"] = id_token
        return f"{self._settings.end_session_endpoint}?{urlencode(params)}"

    async def exchange_code(self, *, code: str, code_verifier: str) -> dict[str, Any]:
        response = await self._http.post(
            self._settings.token_endpoint,
            data={
                "grant_type": "authorization_code",
                "client_id": self._settings.keycloak_client_id,
                "client_secret": self._settings.keycloak_client_secret,
                "code": code,
                "redirect_uri": self._settings.callback_url,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        return response.json()

    async def revoke_refresh_token(self, refresh_token: str) -> None:
        revoke_url = f"{self._settings.keycloak_issuer.rstrip('/')}/protocol/openid-connect/revoke"
        response = await self._http.post(
            revoke_url,
            data={
                "client_id": self._settings.keycloak_client_id,
                "client_secret": self._settings.keycloak_client_secret,
                "token": refresh_token,
                "token_type_hint": "refresh_token",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()

    async def fetch_userinfo(self, access_token: str) -> dict[str, Any]:
        response = await self._http.get(
            self._settings.userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()


def authenticated_user_from_claims(
    claims: dict[str, Any],
    *,
    default_tenant_id: str = "local_demo",
) -> AuthenticatedUser:
    roles = claims.get("roles")
    if not isinstance(roles, list):
        realm_access = claims.get("realm_access") or {}
        roles = realm_access.get("roles") if isinstance(realm_access, dict) else []
    if not isinstance(roles, list):
        roles = []
    email = claims.get("email") or claims.get("preferred_username")
    name = claims.get("name")
    if not name:
        given = claims.get("given_name") or ""
        family = claims.get("family_name") or ""
        name = f"{given} {family}".strip() or None
    return AuthenticatedUser(
        sub=str(claims.get("sub") or ""),
        email=str(email) if email else None,
        name=str(name) if name else None,
        roles=[str(role) for role in roles if str(role).strip()],
        tenant_id=str(claims.get("tenant_id") or default_tenant_id),
    )
