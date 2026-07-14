from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.core.config import Settings, get_settings
from app.routers.auth import create_auth_router
from app.routers.proxy import create_proxy_router
from app.services.oidc import OidcClient
from app.services.session_store import SessionStore


def create_app(
    *,
    settings: Settings | None = None,
    session_store: SessionStore | None = None,
    oidc_client: OidcClient | None = None,
    http_client: httpx.AsyncClient | None = None,
    redis: Redis | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    owns_runtime = session_store is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        local_redis = redis
        local_http = http_client
        close_redis = False
        close_http = False
        if owns_runtime:
            if local_redis is None:
                local_redis = Redis.from_url(app_settings.redis_url, decode_responses=True)
                close_redis = True
            if local_http is None:
                local_http = httpx.AsyncClient(timeout=app_settings.request_timeout_seconds)
                close_http = True
            app.state.session_store = SessionStore(
                local_redis,
                ttl_seconds=app_settings.session_ttl_seconds,
            )
            app.state.oidc_client = OidcClient(app_settings, local_http)
            app.state.http_client = local_http
        else:
            app.state.session_store = session_store
            app.state.oidc_client = oidc_client
            app.state.http_client = http_client
        try:
            yield
        finally:
            if close_http and local_http is not None:
                await local_http.aclose()
            if close_redis and local_redis is not None:
                await local_redis.aclose()

    app = FastAPI(title=app_settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[app_settings.frontend_base_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health/live")
    async def health_live() -> dict[str, str]:
        return {"status": "ok"}

    runtime_session_store = session_store or _AppStateProxy(app, "session_store")
    runtime_oidc = oidc_client or _AppStateProxy(app, "oidc_client")
    runtime_http = http_client or _AppStateProxy(app, "http_client")

    app.include_router(
        create_auth_router(
            settings=app_settings,
            session_store=runtime_session_store,  # type: ignore[arg-type]
            oidc_client=runtime_oidc,  # type: ignore[arg-type]
        )
    )
    app.include_router(
        create_proxy_router(
            settings=app_settings,
            session_store=runtime_session_store,  # type: ignore[arg-type]
            http_client=runtime_http,  # type: ignore[arg-type]
        )
    )
    return app


class _AppStateProxy:
    def __init__(self, app: FastAPI, attr_name: str) -> None:
        self._app = app
        self._attr_name = attr_name

    def __getattr__(self, item):
        target = getattr(self._app.state, self._attr_name)
        return getattr(target, item)


app = create_app()
