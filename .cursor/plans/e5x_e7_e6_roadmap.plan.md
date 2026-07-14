# Post-E5.1 Roadmap Lock (2026-07-15)

Agreed sequence after E5.1 UI confirmation:

```text
E5.x (narrow Kafka hardening)
  → E7 slice (product packaging, not full E7)
  → E6 lab adapter (LangGraph beside AgentOrchestrator, not instead)
```

## E5.x MVP

Status: **implemented (2026-07-15)**

- publish `document.indexed` / `document.index_failed` after worker `process_job`
- quiet Qdrant client/server compatibility warning (`check_compatibility=False` for local 1.12 server)
- keep Postgres job status as source of truth
- out of scope: OCR-only worker, eval topics, transactional outbox

## E7 slice

1. MinIO/S3 for uploads — **done**
2. Compose/deploy profile + worker/API health — **done**
3. Minimal metrics — **done** (`/metrics`, `/metrics/summary`)
4. Prometheus + Grafana ops UI + admin deep-link — **done**

Next: **E6 lab** (LangGraph beside Agent).

Defer: mega admin UI, audit export suite, full report generation, in-app product charts.

## E6 lab

Status: **lab baseline implemented (2026-07-15)**

- thin LangGraph adapter calling existing tools/RBAC — **done**
- feature flag `AGENT_LANGGRAPH_ENABLED` (default off); handwritten Agent remains primary
- unit side-by-side parity tests — **done**
- live API smoke handwritten vs langgraph (`qwen3.5:9b`) — **done** (see `research/e6_handwritten_vs_langgraph_smoke.json`)
- optional next: UI toggle / Grafana label by `provider`
