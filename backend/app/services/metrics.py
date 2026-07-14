"""Minimal process metrics for TaskFlow API and indexing worker.

Baseline exposes Prometheus text format without requiring prometheus_client.
Grafana/Alertmanager remain future hardening.
"""

from __future__ import annotations

from collections import defaultdict
from threading import Lock
from time import perf_counter
from typing import Any, Iterable

from starlette.requests import Request
from starlette.responses import Response

PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _label_key(labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(key), str(value)) for key, value in labels.items()))


def _format_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{key}="{_escape_label(value)}"' for key, value in labels)
    return "{" + inner + "}"


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


class _Counter:
    def __init__(self) -> None:
        self._values: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)
        self._lock = Lock()

    def inc(self, labels: dict[str, str], amount: float = 1.0) -> None:
        key = _label_key(labels)
        with self._lock:
            self._values[key] += amount

    def total(self) -> float:
        with self._lock:
            return float(sum(self._values.values()))

    def samples(self) -> list[tuple[tuple[tuple[str, str], ...], float]]:
        with self._lock:
            return list(self._values.items())


class _Histogram:
    """Simple cumulative histogram with +Inf bucket and sum/count."""

    def __init__(self, buckets: Iterable[float]) -> None:
        cleaned = sorted({float(bucket) for bucket in buckets if bucket > 0})
        self._boundaries = cleaned
        self._counts: dict[tuple[tuple[str, str], ...], list[float]] = {}
        self._sums: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)
        self._lock = Lock()

    def observe(self, labels: dict[str, str], value: float) -> None:
        key = _label_key(labels)
        with self._lock:
            buckets = self._counts.setdefault(key, [0.0] * (len(self._boundaries) + 1))
            placed = False
            for index, boundary in enumerate(self._boundaries):
                if value <= boundary:
                    buckets[index] += 1.0
                    placed = True
                    break
            if not placed:
                buckets[-1] += 1.0
            self._sums[key] += float(value)

    def samples(self) -> list[tuple[tuple[tuple[str, str], ...], list[float], float]]:
        with self._lock:
            return [
                (key, list(counts), float(self._sums[key]))
                for key, counts in self._counts.items()
            ]

    @property
    def boundaries(self) -> list[float]:
        return list(self._boundaries)


class AppMetrics:
    """In-process counters/histograms with Prometheus text + JSON summary."""

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.http_requests = _Counter()
        self.http_duration = _Histogram(
            buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0)
        )
        self.rag_requests = _Counter()
        self.rag_duration = _Histogram(
            buckets=(0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0)
        )
        self.agent_requests = _Counter()
        self.agent_duration = _Histogram(
            buckets=(0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0)
        )
        self.indexing_jobs = _Counter()

    def observe_http(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        if not self.enabled:
            return
        labels = {"method": method, "path": path, "status": str(status_code)}
        self.http_requests.inc(labels)
        self.http_duration.observe({"method": method, "path": path}, duration_seconds)

    def observe_rag(self, *, outcome: str, duration_seconds: float) -> None:
        if not self.enabled:
            return
        labels = {"outcome": outcome}
        self.rag_requests.inc(labels)
        self.rag_duration.observe(labels, duration_seconds)

    def observe_agent(self, *, outcome: str, duration_seconds: float) -> None:
        if not self.enabled:
            return
        labels = {"outcome": outcome}
        self.agent_requests.inc(labels)
        self.agent_duration.observe(labels, duration_seconds)

    def observe_indexing(self, *, result: str) -> None:
        if not self.enabled:
            return
        self.indexing_jobs.inc({"result": result})

    def render_prometheus(self) -> bytes:
        lines: list[str] = []
        _append_counter(
            lines,
            name="taskflow_http_requests_total",
            help_text="HTTP requests handled by the process",
            counter=self.http_requests,
        )
        _append_histogram(
            lines,
            name="taskflow_http_request_duration_seconds",
            help_text="HTTP request latency in seconds",
            histogram=self.http_duration,
        )
        _append_counter(
            lines,
            name="taskflow_rag_requests_total",
            help_text="RAG chat requests by outcome",
            counter=self.rag_requests,
        )
        _append_histogram(
            lines,
            name="taskflow_rag_request_duration_seconds",
            help_text="RAG chat latency in seconds",
            histogram=self.rag_duration,
        )
        _append_counter(
            lines,
            name="taskflow_agent_requests_total",
            help_text="Agent chat requests by outcome",
            counter=self.agent_requests,
        )
        _append_histogram(
            lines,
            name="taskflow_agent_request_duration_seconds",
            help_text="Agent chat latency in seconds",
            histogram=self.agent_duration,
        )
        _append_counter(
            lines,
            name="taskflow_indexing_jobs_total",
            help_text="Indexing jobs finished by result",
            counter=self.indexing_jobs,
        )
        return ("\n".join(lines) + "\n").encode("utf-8")

    def content_type(self) -> str:
        return PROMETHEUS_CONTENT_TYPE

    def summary(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "http_requests_total": self.http_requests.total(),
            "rag_requests_total": self.rag_requests.total(),
            "agent_requests_total": self.agent_requests.total(),
            "indexing_jobs_total": self.indexing_jobs.total(),
        }


def _append_counter(
    lines: list[str],
    *,
    name: str,
    help_text: str,
    counter: _Counter,
) -> None:
    lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} counter")
    samples = counter.samples()
    if not samples:
        lines.append(f"{name} 0")
        return
    for labels, value in samples:
        lines.append(f"{name}{_format_labels(labels)} {value}")


def _append_histogram(
    lines: list[str],
    *,
    name: str,
    help_text: str,
    histogram: _Histogram,
) -> None:
    lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} histogram")
    samples = histogram.samples()
    if not samples:
        return
    for labels, bucket_counts, observed_sum in samples:
        cumulative = 0.0
        for boundary, count in zip(histogram.boundaries, bucket_counts[:-1], strict=True):
            cumulative += count
            bucket_labels = labels + (("le", _format_bucket(boundary)),)
            lines.append(f"{name}_bucket{_format_labels(bucket_labels)} {cumulative}")
        cumulative += bucket_counts[-1]
        inf_labels = labels + (("le", "+Inf"),)
        lines.append(f"{name}_bucket{_format_labels(inf_labels)} {cumulative}")
        lines.append(f"{name}_sum{_format_labels(labels)} {observed_sum}")
        lines.append(f"{name}_count{_format_labels(labels)} {cumulative}")


def _format_bucket(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return format(value, "g")


def request_path_label(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    return request.url.path


def should_skip_http_metrics(path: str) -> bool:
    return path in {"/metrics", "/metrics/summary"} or path.startswith("/health")


async def metrics_http_middleware(request: Request, call_next, metrics: AppMetrics):
    if not metrics.enabled or should_skip_http_metrics(request.url.path):
        return await call_next(request)

    started = perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        metrics.observe_http(
            method=request.method,
            path=request_path_label(request),
            status_code=status_code,
            duration_seconds=perf_counter() - started,
        )


def prometheus_response(metrics: AppMetrics) -> Response:
    return Response(content=metrics.render_prometheus(), media_type=metrics.content_type())
