# Regression Environment Commands

Use these commands from a clean terminal before running M5 document-only or full project regressions.

## 1. Start Docker Services

```bash
cd /home/santera/Projects
docker compose down
docker compose up -d
docker compose ps
```

Expected services:

- `taskflow-postgres` healthy on `5432`
- `taskflow-qdrant` running on `6333` and `6334`

Quick checks:

```bash
docker exec taskflow-postgres pg_isready -U po_user -d po_assistant
curl http://127.0.0.1:6333/collections
```

## 2. Start Backend API

Run this in a separate terminal and keep it open:

```bash
cd /home/santera/Projects/backend
PYTHONPATH=/home/santera/Projects/backend ./.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Expected output:

```text
Application startup complete.
Uvicorn running on http://0.0.0.0:8000
```

Quick health check from another terminal:

```bash
curl http://127.0.0.1:8000/health
```

## 3. Optional Reindex

Only run this if ingestion code, raw data, document fixtures, chunking, OCR, or vision digest evidence changed.

```bash
cd /home/santera/Projects/backend
PYTHONPATH=/home/santera/Projects/backend ./.venv/bin/python scripts/ingest_seed_data.py --recreate
```

Expected end state:

```text
Ingestion complete.
```

## 4. Notes

- Run evaluator commands from `/home/santera/Projects/backend`.
- Use explicit model names in evaluation commands. Do not rely on `DEFAULT_RAG_MODEL` while comparing models.
- If Docker says `permission denied`, use your normal Docker setup or run the compose command with `sudo` for a one-off local run.
