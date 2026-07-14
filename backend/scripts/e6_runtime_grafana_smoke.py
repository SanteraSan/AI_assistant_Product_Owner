#!/usr/bin/env python3
"""Side-by-side agent smoke for handwritten vs langgraph (records one runtime per process)."""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.services.service_jwt import issue_service_jwt

NEWEST_BUCKET = "eeff20cd-fa1a-4603-b90a-11376edb20ff"
AVTO_DOC = "67e5db64-d2b6-4a52-a1be-17f6f62f9251"
MODEL = "qwen3.5:9b"


def _token(*, sub: str, roles: list[str]) -> str:
    settings = get_settings()
    return issue_service_jwt(
        sub=sub,
        tenant_id="local_demo",
        roles=roles,
        secret=settings.service_jwt_secret,
        issuer=settings.service_jwt_issuer,
        audience=settings.service_jwt_audience,
        ttl_seconds=7200,
        name=sub,
        email=f"{sub}@taskflow.local",
    )


def _summarize(data: dict) -> dict:
    tools = []
    for item in data.get("tool_calls") or []:
        if isinstance(item, dict):
            tools.append(
                {
                    "name": item.get("name") or item.get("tool"),
                    "status": item.get("status") or item.get("ok"),
                }
            )
    steps = data.get("steps")
    if isinstance(steps, list):
        steps_value: int | list = len(steps)
    elif isinstance(steps, int):
        steps_value = steps
    else:
        steps_value = 0
    return {
        "provider": data.get("provider"),
        "latency_ms": data.get("latency_ms"),
        "steps": steps_value,
        "tool_calls": tools,
        "answer_preview": (data.get("response") or "")[:240],
    }


def run_scenario(
    client: httpx.Client,
    *,
    token: str,
    message: str,
    session_id: str,
    bucket_id: str | None = None,
    document_ids: list[str] | None = None,
) -> dict:
    payload: dict = {
        "message": message,
        "session_id": session_id,
        "model": MODEL,
        "approach": "agent",
    }
    if bucket_id:
        payload["active_bucket_id"] = bucket_id
        payload["bucket_ids"] = [bucket_id]
    if document_ids:
        payload["document_ids"] = document_ids
    response = client.post(
        "/agent/chat",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=180.0,
    )
    body = response.json() if response.content else {}
    if response.status_code >= 400:
        return {
            "http_status": response.status_code,
            "error": body,
        }
    summary = _summarize(body)
    summary["http_status"] = response.status_code
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--runtime-label", required=True, help="Expected runtime: handwritten|langgraph")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("/home/santera/Projects/research/e6_runtime_grafana_smoke_partial.json"),
    )
    args = parser.parse_args()

    admin = _token(sub="kc-admin", roles=["admin"])
    viewer = _token(sub="kc-viewer", roles=["viewer"])

    scenarios = [
        {
            "id": "list_buckets",
            "role": "admin",
            "message": "Какие buckets доступны в моём тенанте? Кратко перечисли.",
        },
        {
            "id": "list_bucket_files",
            "role": "admin",
            "message": "Какие файлы лежат в активном bucket? Только имена файлов.",
            "bucket_id": NEWEST_BUCKET,
        },
        {
            "id": "analyze_avto",
            "role": "admin",
            "message": "Что изображено на avto.jpg? Ответь кратко по фактам с картинки.",
            "bucket_id": NEWEST_BUCKET,
            "document_ids": [AVTO_DOC],
        },
        {
            "id": "viewer_sql",
            "role": "viewer",
            "message": "Выполни SQL: SELECT 1 AS x. Если нельзя — скажи почему.",
        },
    ]

    results: list[dict] = []
    with httpx.Client(base_url=args.base_url) as client:
        ready = client.get("/health/ready", timeout=10.0)
        features = ready.json().get("features") or {}
        print("ready features:", {k: features.get(k) for k in ("agent_langgraph_enabled", "metrics_enabled")})

        for scenario in scenarios:
            token = admin if scenario["role"] == "admin" else viewer
            print(f"\n=== {scenario['id']} ({args.runtime_label}) ===")
            started = time.perf_counter()
            summary = run_scenario(
                client,
                token=token,
                message=scenario["message"],
                session_id=str(uuid.uuid4()),
                bucket_id=scenario.get("bucket_id"),
                document_ids=scenario.get("document_ids"),
            )
            wall_ms = int((time.perf_counter() - started) * 1000)
            summary["wall_ms"] = wall_ms
            row = {**scenario, "runtime": args.runtime_label, "result": summary}
            results.append(row)
            print(json.dumps(summary, ensure_ascii=False, indent=2))

        metrics = client.get("/metrics", timeout=10.0).text
        runtime_lines = [
            line
            for line in metrics.splitlines()
            if line.startswith("taskflow_agent_requests_total") and "agent_runtime=" in line
        ]

    payload = {
        "name": "e6_runtime_grafana_smoke",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "runtime": args.runtime_label,
        "model": MODEL,
        "scenarios": results,
        "metrics_agent_runtime_lines": runtime_lines,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {args.out}")
    print("metrics lines:")
    for line in runtime_lines:
        print(" ", line)


if __name__ == "__main__":
    main()
