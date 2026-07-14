# E5 Dependencies Checklist

Установи **до** полного smoke E5.1 (Kafka-path indexing).

## 1. Redpanda (Kafka API)

```bash
cd /home/santera/Projects
docker compose --profile e5 up -d redpanda
```

Проверка: порт `19092` слушает (`ss -ltn | rg 19092` или `docker ps | rg redpanda`).

## 2. Python deps

```bash
cd backend
source .venv/bin/activate
pip install aiokafka
```

## 3. Env для Kafka-path

```bash
export KAFKA_ENABLED=true
export KAFKA_BOOTSTRAP_SERVERS=localhost:19092
export KAFKA_INDEXING_TOPIC=taskflow.indexing.requested
export KAFKA_DOCUMENT_EVENTS_TOPIC=taskflow.document.events
export KAFKA_CONSUMER_GROUP=taskflow-indexing-workers
export QDRANT_CHECK_COMPATIBILITY=false
```

Или строки в `backend/.env` (см. `.env.example`).

## 4. Два процесса

```bash
# API
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Worker
python -m scripts.run_indexing_worker
```

При `KAFKA_ENABLED=false` (default) indexing остаётся на FastAPI `BackgroundTasks` — worker не нужен.

## Не нужно для E5.1

- отдельные OCR/eval topics
- transactional outbox
- Kafka UI (опционально позже)
