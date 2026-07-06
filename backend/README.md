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
  "qdrant_collection_exists": true,
  "postgres_available": true
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

Для PO-вопросов можно дополнительно ограничить типы источников:

```bash
curl -s -X POST http://localhost:8000/rag/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Какие проблемы с notifications влияют на enterprise-клиентов?","model":"gemma3:12b","top_k":8,"score_threshold":0.68,"features":["notifications"],"source_types":["incident_note","support_ticket","metric_row","release_note"],"max_sources_per_title":1}' | \
  jq '{model,response,latency_ms,collection,features,source_types,score_threshold,retrieval,diversity,sources:[.sources[] | {score,title,source_type,feature}]}'
```

`max_sources_per_title` помогает не забивать prompt несколькими почти одинаковыми support tickets с одним заголовком. По умолчанию backend уже использует `max_sources_per_title=1`.

Backend берет из Qdrant расширенный пул кандидатов: `candidate_k = top_k * 3`. После `score_threshold` и diversity в prompt попадает максимум `top_k` sources. Поле `retrieval` показывает `requested_top_k`, `candidate_k` и фактический `final_top_k`.

Для вопросов про метрики backend использует простой rule-based query router:

```bash
curl -s -X POST http://localhost:8000/rag/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Какие метрики по notifications изменились у enterprise-клиентов?","model":"qwen2.5:14b","top_k":8,"features":["notifications"],"max_sources_per_title":1}' | \
  jq '{model,response,latency_ms,score_threshold,source_types,query_hints,retrieval,sources:[.sources[] | {score,title,source_type,feature}]}'
```

Если пользователь пишет "без метрик" или похожую фразу, metric hint не применяется:

```bash
curl -s -X POST http://localhost:8000/rag/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Какие проблемы с notifications важны для enterprise-клиентов, без метрик?","model":"qwen2.5:14b","top_k":8,"features":["notifications"],"max_sources_per_title":1}' | \
  jq '{model,response,latency_ms,score_threshold,source_types,query_hints,context_policy,retrieval,sources:[.sources[] | {score,title,source_type,feature}]}'
```

В этом случае `query_hints.metric_negative_marker=true`, `applied_hints=[]`, а prompt получает строгое дополнительное правило не упоминать числовые KPI, проценты, счетчики тикетов, adoption, latency/delay metrics и рекомендации про метрики. Также включается `context_policy.numeric_line_sanitization=true`: backend убирает numeric/KPI-heavy строки из prompt context, но оставляет оригинальные `sources` в API response для отладки. Router не переопределяет явно переданные `source_types` и `score_threshold`; ручные параметры имеют приоритет.

Для Developer-вопросов можно, наоборот, искать в технических источниках:

```bash
curl -s -X POST http://localhost:8000/rag/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Какая техническая причина задержек Slack notifications?","model":"gemma3:12b","top_k":5,"score_threshold":0.68,"features":["notifications"],"source_types":["markdown","openapi","incident_note"]}' | \
  jq '{model,response,latency_ms,collection,features,source_types,score_threshold,sources:[.sources[] | {score,title,source_type,feature}]}'
```

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

## M2: Первый PostgreSQL Слой

PostgreSQL используется как системная память для backend observability: пока без multi-turn memory, но уже с сохранением истории RAG-запросов.

При старте backend автоматически создает минимальные таблицы, если PostgreSQL доступен:

- `rag_request_logs` - сообщение пользователя, ответ модели, latency, выбранная модель, retrieval/router/context policy параметры;
- `rag_source_logs` - sources, которые попали в ответ, включая score, title, source type, source path, metadata и короткий excerpt content.
- `chat_sessions` - логические диалоги пользователя;
- `chat_messages` - user/assistant сообщения внутри session.

Логирование `/chat` и `/rag/chat` работает best-effort: если PostgreSQL временно недоступен, ответ все равно вернется, а ошибка попадет в backend logs. История пока не подмешивается в prompt: RAG остается single-turn, а PostgreSQL только сохраняет conversation history для будущего этапа.

Проверить доступность PostgreSQL через backend:

```bash
curl http://localhost:8000/health | jq '{postgres_available,qdrant_collection_exists,ollama_available}'
```

Посмотреть последние RAG-запросы:

```bash
docker exec -it taskflow-postgres psql -U po_user -d po_assistant \
  -c "select id, created_at, model, latency_ms, jsonb_array_length(source_types) as source_type_count from rag_request_logs order by created_at desc limit 5;"
```

Посмотреть sources для последнего RAG-запроса:

```bash
docker exec -it taskflow-postgres psql -U po_user -d po_assistant \
  -c "select source_index, title, source_type, round(score::numeric, 3) as score from rag_source_logs where request_log_id = (select id from rag_request_logs order by created_at desc limit 1) order by source_index;"
```

Проверить последние chat messages:

```bash
docker exec -it taskflow-postgres psql -U po_user -d po_assistant \
  -c "select session_id, role, left(content, 80) as content_preview, model, latency_ms, created_at from chat_messages order by created_at desc limit 10;"
```

Продолжить ту же session можно, передав `session_id` из предыдущего ответа:

```bash
curl -s -X POST http://localhost:8000/rag/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"<SESSION_ID_FROM_PREVIOUS_RESPONSE>","message":"А какие из этих проблем самые критичные?","model":"gemma3:12b","top_k":5}' | \
  jq '{session_id,user_message_id,assistant_message_id,model,latency_ms,response}'
```

Важно: на текущем этапе `session_id` только связывает записи в PostgreSQL. Backend еще не использует прошлые сообщения как context для следующего RAG prompt.
