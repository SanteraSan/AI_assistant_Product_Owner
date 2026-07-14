from app.services.metrics import AppMetrics, should_skip_http_metrics


def test_metrics_prometheus_contains_counters_after_observe() -> None:
    metrics = AppMetrics(enabled=True)
    metrics.observe_http(
        method="GET",
        path="/chat/sessions",
        status_code=200,
        duration_seconds=0.12,
    )
    metrics.observe_rag(outcome="success", duration_seconds=1.5)
    metrics.observe_agent(outcome="error", duration_seconds=0.4)
    metrics.observe_indexing(result="completed")

    text = metrics.render_prometheus().decode("utf-8")
    assert "taskflow_http_requests_total" in text
    assert 'path="/chat/sessions"' in text
    assert 'status="200"' in text
    assert "taskflow_rag_requests_total" in text
    assert 'outcome="success"' in text
    assert "taskflow_agent_requests_total" in text
    assert "taskflow_indexing_jobs_total" in text
    assert 'result="completed"' in text
    assert "taskflow_http_request_duration_seconds_bucket" in text


def test_metrics_summary_totals() -> None:
    metrics = AppMetrics(enabled=True)
    metrics.observe_rag(outcome="success", duration_seconds=0.2)
    metrics.observe_rag(outcome="error", duration_seconds=0.1)
    metrics.observe_indexing(result="failed")

    summary = metrics.summary()
    assert summary["enabled"] is True
    assert summary["rag_requests_total"] == 2.0
    assert summary["indexing_jobs_total"] == 1.0
    assert summary["http_requests_total"] == 0.0


def test_metrics_disabled_is_noop() -> None:
    metrics = AppMetrics(enabled=False)
    metrics.observe_http(
        method="GET",
        path="/x",
        status_code=200,
        duration_seconds=0.01,
    )
    assert metrics.summary()["http_requests_total"] == 0.0
    assert "taskflow_http_requests_total 0" in metrics.render_prometheus().decode("utf-8")


def test_should_skip_health_and_metrics_paths() -> None:
    assert should_skip_http_metrics("/health/live") is True
    assert should_skip_http_metrics("/metrics") is True
    assert should_skip_http_metrics("/rag/chat") is False
