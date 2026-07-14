# E5 Kafka / Redpanda — Event-Driven Indexing

## Goal

Durable async indexing: API accepts document → Postgres job → Kafka event → worker runs `DocumentIndexingService.process_jobs`.

Postgres remains source of truth for job status. Redis stays for rate limits.

## E5.1 MVP (narrow)

In scope:
- Redpanda (Kafka API) in compose profile `e5`
- event `indexing.requested` with `job_ids`
- producer from commit / ingest / retry-indexing when `KAFKA_ENABLED=true`
- consumer worker script
- fallback: `KAFKA_ENABLED=false` → existing FastAPI `BackgroundTasks`

Out of scope (later):
- full pipeline events (`parsed` / `chunked` / `embedded`)
- evaluation / report topics
- OCR-only worker split
- exactly-once / transactional outbox (document as future hardening)

## Run

```bash
docker compose --profile e5 up -d redpanda
cd backend
# .env or export:
export KAFKA_ENABLED=true
export KAFKA_BOOTSTRAP_SERVERS=localhost:19092

# terminal A — API
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# terminal B — worker
python -m scripts.run_indexing_worker
```

Smoke: upload/ingest a small txt → poll `/documents/{id}/status` until `indexed` while worker logs the event.

**UI confirmed (2026-07-15):** image upload → vision generate + embeddings via worker → RAG grounded description in bucket chat.
