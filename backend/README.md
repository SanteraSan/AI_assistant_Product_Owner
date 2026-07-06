# Backend M0: Ollama Smoke Test

Минимальный `FastAPI` backend для проверки локального inference через Ollama.

На этом этапе нет RAG, Qdrant и PostgreSQL. Цель M0 - убедиться, что backend умеет отправить запрос в локальную модель и вернуть ответ.

## Что Нужно Установить

На новой Ubuntu/Debian-системе:

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv curl
```

Docker понадобится для следующих этапов:

```bash
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker "$USER"
```

После добавления пользователя в группу `docker` нужно перелогиниться или выполнить:

```bash
newgrp docker
```

Ollama лучше установить официальным скриптом:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Проверить GPU в обычном терминале:

```bash
nvidia-smi
```

Если `nvidia-smi` не видит драйвер, сначала нужно починить NVIDIA-драйвер. Без этого Ollama может работать на CPU, но будет медленно.

## Первая Модель

Скачать маленькую модель для smoke test:

```bash
ollama pull qwen2.5:0.5b
```

Проверить напрямую:

```bash
ollama run qwen2.5:0.5b
```

## Запуск Backend

Из папки проекта:

```bash
cd /home/santera/Projects/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Проверка

Health check:

```bash
curl http://localhost:8000/health
```

Chat request:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Привет! Ответь одним предложением, что ты работаешь локально.","model":"qwen2.5:0.5b"}'
```

Ожидаемый результат:

- backend отвечает HTTP 200;
- поле `provider` равно `ollama`;
- поле `model` равно выбранной модели;
- поле `latency_ms` показывает время ответа;
- поле `response` содержит текст модели.

## Если Ollama Не Доступна

Проверить сервис:

```bash
ollama list
```

Если команда не работает, запустить:

```bash
ollama serve
```

В отдельном терминале снова проверить `/health`.

## Что Коммитить После M0

После успешного smoke test:

```bash
git status
git add backend research/LESSONS_LEARNED.md
git commit -m "feat: add ollama smoke test backend"
git push
```

## M1: Single-Collection RAG

На M1 backend получает первый RAG-путь:

```text
raw seed files -> chunks -> Ollama embeddings -> Qdrant documents -> /rag/chat -> Ollama answer with sources
```

PostgreSQL поднимается сразу, но история чата и таблицы будут подключены следующим шагом. В M1 основной фокус - Qdrant и первый grounded answer.

### Поднять Qdrant И PostgreSQL

Из корня проекта:

```bash
cd /home/santera/Projects
docker compose up -d
docker ps
```

Проверить Qdrant:

```bash
curl http://localhost:6333/healthz
```

### Embedding-Модель

Скачать embedding-модель:

```bash
ollama pull nomic-embed-text
```

Проверить, что модель есть:

```bash
ollama list
```

### Обновить Python-Зависимости

Из папки backend:

```bash
cd /home/santera/Projects/backend
source .venv/bin/activate
pip install -r requirements.txt
```

Если `.env` уже создан раньше, обнови его по `backend/.env.example` или добавь новые переменные вручную.

### Загрузить Seed-Данные В Qdrant

Из папки backend:

```bash
cd /home/santera/Projects/backend
source .venv/bin/activate
python -m scripts.ingest_seed_data --recreate
```

Ожидаемый результат:

- script прочитает `data/raw`;
- создаст chunks;
- получит embeddings через `nomic-embed-text`;
- создаст Qdrant collection `documents`;
- загрузит chunks в Qdrant.

### Проверить Health

```bash
curl http://localhost:8000/health | jq
```

Ожидаемые важные поля:

```json
{
  "ollama_available": true,
  "embedding_model": "nomic-embed-text",
  "qdrant_collection": "documents",
  "qdrant_collection_exists": true
}
```

### Первый RAG-Запрос

```bash
curl -s -X POST http://localhost:8000/rag/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Какие проблемы с notifications влияют на enterprise-клиентов?","model":"gemma3:12b","top_k":5}' | \
  jq '{model,response,latency_ms,collection,sources}'
```

Если ответ содержит `sources`, значит первый single-collection RAG работает.

Для более чистого retrieval на маленьком seed dataset можно уменьшить `top_k` и добавить `score_threshold`:

```bash
curl -s -X POST http://localhost:8000/rag/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Какие проблемы с notifications влияют на enterprise-клиентов?","model":"gemma3:12b","top_k":5,"score_threshold":0.68}' | \
  jq '{model,response,latency_ms,collection,score_threshold,sources:[.sources[] | {score,title,source_type,feature}]}'
```

Такой `jq` выводит компактные sources без полного `content`, чтобы терминал не превращался в простыню.

Можно также добавить metadata filter по feature:

```bash
curl -s -X POST http://localhost:8000/rag/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Какие проблемы с notifications влияют на enterprise-клиентов?","model":"gemma3:12b","top_k":5,"score_threshold":0.68,"features":["notifications"]}' | \
  jq '{model,response,latency_ms,collection,features,score_threshold,sources:[.sources[] | {score,title,source_type,feature}]}'
```

`features` фильтрует Qdrant payload до сборки prompt. Например `["notifications"]` не даст попасть в prompt chunks по `csv_import` или `search`.

Если `features` не передавать, backend попробует определить их сам простым rule-based extractor:

```bash
curl -s -X POST http://localhost:8000/rag/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Какие проблемы с notifications влияют на enterprise-клиентов?","model":"gemma3:12b","top_k":5,"score_threshold":0.68}' | \
  jq '{model,response,latency_ms,collection,features,score_threshold,sources:[.sources[] | {score,title,source_type,feature}]}'
```

Ручное поле `features` имеет приоритет над автоопределением. Это удобно для отладки retrieval.

Если нужно увидеть полный контекст, который попал в ответ, используй:

```bash
curl -s -X POST http://localhost:8000/rag/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Какие проблемы с notifications влияют на enterprise-клиентов?","model":"gemma3:12b","top_k":3}' | \
  jq '{model,response,latency_ms,collection,sources}'
```
