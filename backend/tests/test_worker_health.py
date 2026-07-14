from starlette.testclient import TestClient

from app.services.worker_health import build_worker_health_app


def test_worker_health_live_ok() -> None:
    async def ready_probe():
        return {"status": "ready", "service": "indexing-worker"}

    client = TestClient(build_worker_health_app(ready_probe=ready_probe))
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_worker_health_ready_degraded() -> None:
    async def ready_probe():
        return {"status": "degraded", "dependencies": {"postgres_available": False}}

    client = TestClient(build_worker_health_app(ready_probe=ready_probe))
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_worker_health_exposes_metrics_when_enabled() -> None:
    from app.services.metrics import AppMetrics

    metrics = AppMetrics(enabled=True)
    metrics.observe_indexing(result="completed")

    async def ready_probe():
        return {"status": "ready"}

    client = TestClient(build_worker_health_app(ready_probe=ready_probe, metrics=metrics))
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "taskflow_indexing_jobs_total" in response.text
    assert client.get("/metrics/summary").json()["indexing_jobs_total"] == 1.0
