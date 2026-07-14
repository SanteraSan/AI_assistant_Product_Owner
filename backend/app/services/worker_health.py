"""Lightweight health + metrics HTTP server for the indexing worker process."""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from uvicorn import Config, Server

from app.services.metrics import AppMetrics, prometheus_response

logger = logging.getLogger(__name__)

ReadyProbe = Callable[[], Awaitable[dict[str, Any]]]


def build_worker_health_app(
    *,
    ready_probe: ReadyProbe,
    metrics: AppMetrics | None = None,
) -> Starlette:
    async def live(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "indexing-worker"})

    async def ready(_: Request) -> JSONResponse:
        snapshot = await ready_probe()
        status_code = 200 if snapshot.get("status") == "ready" else 503
        return JSONResponse(snapshot, status_code=status_code)

    routes = [
        Route("/health/live", live, methods=["GET"]),
        Route("/health/ready", ready, methods=["GET"]),
        Route("/health", live, methods=["GET"]),
    ]
    if metrics is not None and metrics.enabled:

        async def metrics_prometheus(_: Request):
            return prometheus_response(metrics)

        async def metrics_summary(_: Request) -> JSONResponse:
            return JSONResponse(metrics.summary())

        routes.extend(
            [
                Route("/metrics", metrics_prometheus, methods=["GET"]),
                Route("/metrics/summary", metrics_summary, methods=["GET"]),
            ]
        )

    return Starlette(routes=routes)


async def serve_worker_health(
    *,
    host: str,
    port: int,
    ready_probe: ReadyProbe,
    metrics: AppMetrics | None = None,
) -> Server:
    app = build_worker_health_app(ready_probe=ready_probe, metrics=metrics)
    config = Config(app=app, host=host, port=port, log_level="warning")
    server = Server(config=config)
    logger.info("Indexing worker health listening on http://%s:%s", host, port)
    return server
