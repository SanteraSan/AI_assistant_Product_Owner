from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient, MockTransport, Request, Response

from app.core.config import Settings
from app.main import create_app
from app.services.oidc import OidcClient, authenticated_user_from_claims
from app.services.security import code_challenge_s256, generate_code_verifier
from app.services.service_jwt import AuthenticatedUser, decode_service_jwt, issue_service_jwt
from app.services.session_store import SessionStore


class FakeRedis:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def setex(self, key: str, _ttl: int, value: str) -> None:
        self._data[key] = value

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def aclose(self) -> None:
        return None


def test_pkce_challenge_is_deterministic_for_verifier() -> None:
    verifier = "test-verifier-value-1234567890"
    assert code_challenge_s256(verifier) == code_challenge_s256(verifier)
    assert code_challenge_s256(verifier) != code_challenge_s256(generate_code_verifier())


def test_service_jwt_roundtrip_contains_identity_claims() -> None:
    user = AuthenticatedUser(
        sub="user-1",
        email="admin@local",
        name="Admin Local",
        roles=["admin", "analyst"],
        tenant_id="local_demo",
    )
    secret = "service-jwt-test-secret-32bytes-min"
    token = issue_service_jwt(
        user=user,
        secret=secret,
        issuer="taskflow-bff",
        audience="taskflow-backend",
        ttl_seconds=60,
        request_id="req-1",
    )
    claims = decode_service_jwt(
        token,
        secret=secret,
        issuer="taskflow-bff",
        audience="taskflow-backend",
    )
    assert claims["sub"] == "user-1"
    assert claims["tenant_id"] == "local_demo"
    assert claims["roles"] == ["admin", "analyst"]
    assert claims["request_id"] == "req-1"


def test_authenticated_user_from_claims_reads_tenant_and_roles() -> None:
    user = authenticated_user_from_claims(
        {
            "sub": "abc",
            "email": "viewer@local",
            "tenant_id": "local_demo",
            "roles": ["viewer"],
        }
    )
    assert user.sub == "abc"
    assert user.tenant_id == "local_demo"
    assert user.roles == ["viewer"]


@pytest.mark.asyncio
async def test_login_redirects_to_keycloak_with_pkce() -> None:
    settings = Settings(
        keycloak_issuer="http://localhost:8080/realms/taskflow",
        keycloak_client_id="taskflow-bff",
        keycloak_client_secret="secret",
        bff_public_base_url="http://localhost:8001",
        frontend_base_url="http://localhost:5173",
        backend_base_url="http://localhost:8000",
        service_jwt_secret="service-secret",
    )
    redis = FakeRedis()
    session_store = SessionStore(redis, ttl_seconds=3600)  # type: ignore[arg-type]
    http_client = AsyncClient()
    app = create_app(
        settings=settings,
        session_store=session_store,
        oidc_client=OidcClient(settings, http_client),
        http_client=http_client,
        redis=redis,  # type: ignore[arg-type]
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/auth/login", follow_redirects=False)
    await http_client.aclose()
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("http://localhost:8080/realms/taskflow/protocol/openid-connect/auth?")
    assert "code_challenge_method=S256" in location
    assert "client_id=taskflow-bff" in location


@pytest.mark.asyncio
async def test_callback_creates_session_and_me_returns_user() -> None:
    settings = Settings(
        keycloak_issuer="http://localhost:8080/realms/taskflow",
        keycloak_client_id="taskflow-bff",
        keycloak_client_secret="secret",
        bff_public_base_url="http://localhost:8001",
        frontend_base_url="http://localhost:5173",
        backend_base_url="http://localhost:8000",
        service_jwt_secret="service-secret",
    )
    redis = FakeRedis()
    session_store = SessionStore(redis, ttl_seconds=3600)  # type: ignore[arg-type]

    async def handler(request: Request) -> Response:
        assert str(request.url).endswith("/protocol/openid-connect/token")
        # Minimal unsigned JWT payload for claims extraction in callback.
        import base64
        import json

        payload = base64.urlsafe_b64encode(
            json.dumps(
                {
                    "sub": "user-42",
                    "email": "admin@local",
                    "name": "Admin Local",
                    "tenant_id": "local_demo",
                    "roles": ["admin"],
                }
            ).encode()
        ).rstrip(b"=").decode()
        access_token = f"aaa.{payload}.bbb"
        return Response(
            200,
            json={
                "access_token": access_token,
                "refresh_token": "refresh-1",
                "id_token": "id-1",
                "token_type": "Bearer",
            },
        )

    http_client = AsyncClient(transport=MockTransport(handler))
    oidc_client = OidcClient(settings, http_client)
    app = create_app(
        settings=settings,
        session_store=session_store,
        oidc_client=oidc_client,
        http_client=http_client,
        redis=redis,  # type: ignore[arg-type]
    )

    from app.services.session_store import LoginState

    await session_store.save_login_state(
        LoginState(state="state-1", code_verifier="verifier-1", return_to="http://localhost:5173/")
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        callback = await client.get(
            "/auth/callback",
            params={"code": "auth-code", "state": "state-1"},
            follow_redirects=False,
        )
        assert callback.status_code == 302
        assert callback.headers["location"] == "http://localhost:5173/"
        assert settings.session_cookie_name in callback.cookies

        me = await client.get("/auth/me")
        assert me.status_code == 200
        body = me.json()
        assert body["id"] == "user-42"
        assert body["tenantId"] == "local_demo"
        assert body["roles"] == ["admin"]
        assert body["csrfToken"]

    await http_client.aclose()


@pytest.mark.asyncio
async def test_proxy_rejects_unauthenticated_and_missing_csrf() -> None:
    settings = Settings(
        keycloak_issuer="http://localhost:8080/realms/taskflow",
        keycloak_client_id="taskflow-bff",
        keycloak_client_secret="secret",
        bff_public_base_url="http://localhost:8001",
        frontend_base_url="http://localhost:5173",
        backend_base_url="http://localhost:8000",
        service_jwt_secret="service-jwt-test-secret-32bytes-min",
    )
    redis = FakeRedis()
    session_store = SessionStore(redis, ttl_seconds=3600)  # type: ignore[arg-type]
    http_client = AsyncClient()
    app = create_app(
        settings=settings,
        session_store=session_store,
        oidc_client=OidcClient(settings, http_client),
        http_client=http_client,
        redis=redis,  # type: ignore[arg-type]
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        unauth = await client.get("/api/health/live")
        assert unauth.status_code == 401

        session = await session_store.create_session(
            user=AuthenticatedUser(
                sub="user-1",
                email="admin@local",
                name="Admin",
                roles=["admin"],
                tenant_id="local_demo",
            ),
            access_token="access",
            refresh_token=None,
            id_token=None,
        )
        client.cookies.set(settings.session_cookie_name, session.session_id)
        missing_csrf = await client.post("/api/chat/sessions", json={})
        assert missing_csrf.status_code == 403

    await http_client.aclose()
