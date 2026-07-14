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

## E7 slice (next)

1. MinIO/S3 for uploads — **done**
2. Pick one more later: compose/deploy profile + worker health **or** minimal metrics

Defer: mega admin UI, audit export suite, full report generation.

## E6 lab (after E7 slice)

- thin LangGraph (or similar) adapter calling existing tools/RBAC
- side-by-side smoke vs handwritten Agent
- goal: learn framework trade-offs, not rewrite core
