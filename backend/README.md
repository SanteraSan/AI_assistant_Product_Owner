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

Для `metric_intent` router не только выставляет metric-oriented `source_types`, но и помечает `metric_row` как обязательный source type. Если обычный vector search не дал `metric_row` в candidate pool, `RagService` делает supplemental search по `metric_row` и добавляет найденные metric chunks перед diversity/top-k. Это защищает metric questions от ситуации, когда более текстовые incident/support/release chunks вытесняют сами метрики.

Supplemental search для обязательных source types остается ограниченным по `features` и `source_type`, но не применяет повторно общий `score_threshold`. Это важно для summary-обогащенных follow-up запросов: длинный retrieval query может немного снизить cosine score metric rows, хотя router уже явно требует metric evidence.

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

Основной путь создания и изменения таблиц теперь проходит через Alembic migrations:

- `rag_request_logs` - сообщение пользователя, ответ модели, latency, выбранная модель, retrieval/router/context policy параметры;
- `rag_source_logs` - sources, которые попали в ответ, включая score, title, source type, source path, metadata и короткий excerpt content.
- `chat_sessions` - логические диалоги пользователя;
- `chat_messages` - user/assistant сообщения внутри session.
- `conversation_summaries` - компактный rule-based summary длинных sessions для M4.3.

Применить миграции:

```bash
cd /home/santera/Projects/backend
source .venv/bin/activate
alembic upgrade head
alembic current
```

Для local demo сохранён fallback `DATABASE_AUTO_CREATE_TABLES=true`: при старте backend может создать таблицы через SQLAlchemy metadata, если миграции ещё не запускались. После перехода на migration discipline лучше выставить `DATABASE_AUTO_CREATE_TABLES=false` и поднимать/обновлять схему только через Alembic.

Логирование `/chat` и `/rag/chat` работает best-effort: если PostgreSQL временно недоступен, ответ все равно вернется, а ошибка попадет в backend logs. Полная история не подмешивается в prompt напрямую; conversation context слои M4 используют ее только для управляемого построения `retrieval_query`.

Проверить доступность PostgreSQL через backend:

```bash
curl http://localhost:8000/health | jq '{postgres_available,qdrant_collection_exists,ollama_available}'
```

Начиная с backend hardening этапа доступны отдельные health endpoints:

```bash
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready | jq
```

- `/health/live` проверяет, что FastAPI process отвечает.
- `/health/ready` проверяет готовность зависимостей: PostgreSQL, Qdrant collection и Ollama.
- `/health` оставлен совместимым и дополнительно показывает readiness status, модели и request limits.

Request limits задаются через `.env`:

```bash
MAX_CHAT_MESSAGE_CHARS=8000
MAX_RAG_TOP_K=20
MAX_FILTER_VALUES=50
MAX_FILTER_VALUE_CHARS=512
```

Каждый HTTP request получает `X-Request-ID`:

```bash
curl -i http://localhost:8000/health/live -H "X-Request-ID: demo-request-1"
```

Если header не передан, backend сгенерирует новый request id. Ошибки API возвращают `request_id` в JSON body и `X-Request-ID` в headers, чтобы ответ пользователя можно было связать с backend logs.

Redis используется как coordination layer для rate limiting, а Ollama-вызовы защищены local concurrency guard:

```bash
cd /home/santera/Projects
docker compose up -d redis
docker exec taskflow-redis redis-cli ping
```

Связанные `.env` настройки:

```bash
REDIS_ENABLED=true
REDIS_URL=redis://localhost:6379/0
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=60
RATE_LIMIT_WINDOW_SECONDS=60
RATE_LIMIT_FAIL_OPEN=true
OLLAMA_MAX_CONCURRENCY=2
OLLAMA_QUEUE_TIMEOUT_SECONDS=5
```

Локальный burst smoke:

```bash
cd /home/santera/Projects
backend/.venv/bin/python backend/scripts/run_http_burst_smoke.py \
  --url http://127.0.0.1:8000/chat \
  --requests 1000 \
  --concurrency 50 \
  --model qwen3.5:9b
```

Цель smoke не в том, чтобы локальная машина одновременно сгенерировала 1000 LLM-ответов, а в том, чтобы backend вернул управляемые `200/429/503` и не уронил FastAPI/Ollama.

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

Важно: PostgreSQL хранит полную chat history, но в prompt не подставляется вся переписка. Начиная с M4.1/M4.3 backend использует историю только для построения `retrieval_query`: сначала recent messages, а для длинных sessions - компактный `conversation_summaries`.

## M3: RAG Evaluation Runs В PostgreSQL

Evaluation layer сохраняет результаты модельных прогонов в PostgreSQL вместо локальных одноразовых `.jsonl` файлов.

Новые таблицы:

- `evaluation_runs` - один запуск evaluation: название, checklist version, список моделей, статус, notes;
- `evaluation_results` - результат одного scenario/model: prompt, response, latency, sources summary, retrieval/router/context policy и quality flags.

Для запуска нужен поднятый backend, потому что script проверяет полный API path через `/rag/chat`:

```bash
cd /home/santera/Projects/backend
source .venv/bin/activate
python -m scripts.run_rag_evaluation --models gemma3:12b --limit-scenarios 1 --top-k 3
```

Полный прогон по нескольким моделям:

```bash
python -m scripts.run_rag_evaluation \
  --models qwen2.5:7b-instruct-q8_0 qwen2.5:14b gemma3:12b \
  --top-k 5 \
  --notes "Manual full checklist run"
```

Sales-gold (этап C, 4 сценария через `/rag/chat` + `SalesComposer`). `skip` (`model_unavailable`, нет ключа, `external_scope_not_synthetic`) не красит `evaluation_status=failed`:

```bash
python -m scripts.run_rag_evaluation \
  --suite sales-gold \
  --approach local_only \
  --provider ollama \
  --models qwen3.5:9b \
  --top-k 8 \
  --notes "Sales gold Ollama"

python -m scripts.run_rag_evaluation \
  --suite sales-gold \
  --approach external \
  --provider gemini \
  --models gemini-3.6-flash \
  --top-k 8 \
  --notes "Sales gold Gemini"

python -m scripts.run_rag_evaluation \
  --suite sales-catalog \
  --approach local_only \
  --models qwen3.5:9b \
  --top-k 8 \
  --notes "Sales catalog Ollama"
```

Legacy checklist без `--suite` ведёт себя как раньше (`--suite legacy`).

Посмотреть последние evaluation runs:

```bash
docker exec -it taskflow-postgres psql -U po_user -d po_assistant \
  -c "select id, name, status, models, scenario_count, started_at, completed_at from evaluation_runs order by started_at desc limit 5;"
```

Посмотреть результаты последнего run:

```bash
docker exec -it taskflow-postgres psql -U po_user -d po_assistant \
  -c "select scenario_id, model, latency_ms, source_count, quality_flags, error from evaluation_results where run_id = (select id from evaluation_runs order by started_at desc limit 1) order by created_at;"
```

Compact reporting без ручного SQL:

```bash
python -m scripts.report_evaluation_runs list --limit 5
python -m scripts.report_evaluation_runs summary
python -m scripts.report_evaluation_runs summary --run-id <EVALUATION_RUN_ID>
```

`summary` показывает агрегаты по моделям и сценариям: среднюю latency, среднее число sources, ошибки, zero-source cases и failed quality flags.

## M4.1: Follow-Up Aware RAG

Backend умеет использовать recent chat history для коротких follow-up вопросов внутри одной `session_id`.

Пример:

```bash
FIRST_RESPONSE=$(curl -s -X POST http://localhost:8000/rag/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Какие проблемы с notifications влияют на enterprise-клиентов?","model":"qwen2.5:7b-instruct-q8_0","top_k":5}')

SESSION_ID=$(echo "$FIRST_RESPONSE" | jq -r '.session_id')

curl -s -X POST http://localhost:8000/rag/chat \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"message\":\"А какие из этих проблем самые критичные?\",\"model\":\"qwen2.5:7b-instruct-q8_0\",\"top_k\":5}" | \
  jq '{session_id,conversation_context,retrieval,response}'
```

`conversation_context` показывает, использовалась ли история:

```json
{
  "used": true,
  "mode": "follow_up_rewrite",
  "follow_up_detected": true,
  "history_messages_used": 2,
  "retrieval_query": "А какие из этих проблем самые критичные? Предыдущая тема: Какие проблемы с notifications влияют на enterprise-клиентов? Ключевые features из предыдущего контекста: notifications.",
  "carried_features": ["notifications"],
  "current_features": []
}
```

M4.1 намеренно использует rule-based rewrite, а не LLM-based rewrite. История влияет на retrieval query, но не заменяет оригинальный вопрос пользователя в prompt. Если текущий вопрос явно содержит новую feature, например `А что с csv_import?`, backend считает это topic switch и не переносит старую тему `notifications`.

## M4.2: Follow-Up Policy Hardening

M4.2 укрепляет M4.1 без добавления long-term memory или summary.

Что покрыто:

- action-plan follow-up: `Что с этим делать в первую очередь?`;
- explicit topic switch: `Ок, забудь notifications, а теперь про permissions`;
- follow-up metric intent: `А какие метрики по ним изменились?`;
- follow-up no-metrics: `А можешь без метрик?`;
- follow-up incident: `А что было в мартовском инциденте?`.

Для явного topic switch backend может санитизировать retrieval query. Например исходное сообщение `Ок, забудь notifications, а теперь про permissions` превращается в retrieval query `а теперь про permissions`, чтобы слово `notifications` из forget-clause не загрязняло поиск.

Debug metadata стало чуть богаче:

```json
{
  "topic_switch_detected": true,
  "decision_reason": "current_message_has_explicit_topic_feature",
  "retrieval_query": "а теперь про permissions",
  "current_features": ["permissions"]
}
```

Full regression M4.2: 5 моделей x 15 сценариев = 75 результатов, `errors=0`, `zero_sources=0`, `failed_flags=0`.

## M4.3: Conversation Summary

M4.3 добавляет компактную session summary для длинных диалогов, где последних 4 сообщений уже недостаточно, чтобы понять, к какой теме относится follow-up.

Границы этапа:

- summary строится rule-based/extractive, без LLM-based summarization;
- summary влияет на retrieval query, но не заменяет оригинальный вопрос в prompt;
- explicit topic switch имеет приоритет и не использует summary;
- триггеры summary: оценочный token budget, fallback по числу сообщений, stale summary после нескольких новых сообщений, session idle boundary;
- unload Ollama model не является trigger, потому что это инфраструктурное событие, а не lifecycle диалога.

Новая таблица:

- `conversation_summaries` - `session_id`, `summary`, `features`, `message_count_at_update`, `metadata_json`, timestamps.

Debug metadata в `conversation_context` теперь показывает summary-состояние:

```json
{
  "summary_available": true,
  "summary_used": true,
  "summary_updated": false,
  "summary_message_count": 8,
  "summary_features": ["notifications"],
  "summary_mode": "stored_summary",
  "summary_reason": "stored_summary_fresh"
}
```

Пример длинного follow-up:

```bash
python -m scripts.run_rag_evaluation \
  --base-url http://localhost:8000 \
  --models qwen2.5:7b-instruct-q8_0 \
  --scenarios summary_long_follow_up summary_topic_switch summary_metric_follow_up summary_negative_metric_follow_up \
  --notes "M4.3 summary smoke"
```

Targeted M4.3 run `d48f20eb-0289-44f2-8832-c47de7e99863`: 4 новых summary scenarios x 1 модель, `errors=0`, `zero_sources=0`, `failed_flags=0`.

Full regression M4.3 run `35a9f4df-bf83-4643-9623-d179735016fd`: 5 моделей x 19 сценариев = 95 результатов, `errors=0`, `zero_sources=0`, `failed_flags=0`.

## M4.4: LLM-Based Structured Summary

M4.4 добавляет production-like режим summary: локальная LLM строит структурированный JSON, а rule-based summary остается fallback.

Настройки:

```bash
CONVERSATION_SUMMARY_STRATEGY=hybrid
CONVERSATION_SUMMARY_MODEL=gemma4:12b
CONVERSATION_SUMMARY_TEMPERATURE=0.0
```

Поддерживаемые стратегии:

- `rule_based` - старый M4.3 режим без вызова LLM;
- `llm` - пробовать LLM summary;
- `hybrid` - пробовать LLM summary, но при ошибке JSON/валидации сохранить rule-based summary.

LLM summary возвращает JSON:

```json
{
  "main_topics": ["notifications"],
  "user_goals": ["понять критичные проблемы enterprise-клиентов"],
  "decisions": [],
  "open_questions": [],
  "constraints": [],
  "summary": "Пользователь обсуждает проблемы notifications..."
}
```

Backend валидирует JSON и сохраняет structured summary в `conversation_summaries.metadata_json`. Важно: `features` для retrieval по-прежнему извлекаются `FeatureExtractor` из реального текста диалога, а не берутся на веру из LLM summary.

Новые debug fields:

```json
{
  "summary_strategy": "hybrid",
  "summary_model": "gemma4:12b",
  "summary_structured": {
    "summary": "..."
  },
  "summary_fallback_used": false,
  "summary_validation_error": null
}
```

Targeted M4.4 run `7337aeab-9946-4447-b4ba-258ca56654a4`: `llm_summary_structured` x 1 модель, `errors=0`, `failed_flags=0`.

Targeted memory regression `1b58271c-9955-4c03-b7f5-7e3ef93b6ac1`: 5 summary/memory scenarios x 1 модель, `errors=0`, `zero_sources=0`, `failed_flags=0`.

Diagnostic full run `31d78815-3424-4270-9d7b-d8a5befd2f0f` поймал router-priority regression: LLM-summary добавил technical markers, и explicit metric follow-up иногда не получал `metric_row`. После fix explicit metric question markers имеют приоритет над technical markers из summary.

Clean full regression M4.4 run `8fd546bb-ea64-426e-bd2d-d5350f9becc1`: 5 моделей x 20 сценариев = 100 результатов, `errors=0`, `zero_sources=0`, `failed_flags=0`.

## M4.5: Prompt Memory Budget

M4.5 добавляет контролируемую conversation memory в финальный RAG prompt. Summary по-прежнему не является evidence: факты о продукте, метрики и причины инцидентов должны приходить из Qdrant sources.

Настройки:

```bash
CONVERSATION_MEMORY_ENABLED=true
CONVERSATION_MEMORY_TOKEN_BUDGET=350
CONVERSATION_MEMORY_RECENT_MESSAGES=4
```

Prompt memory включает:

- structured summary диалога;
- цели пользователя из LLM/rule-based summary;
- последние user messages;
- debug metadata `conversation_context.prompt_memory`.

Пример debug:

```json
{
  "prompt_memory": {
    "used": true,
    "included": ["summary", "user_goals", "recent_user_messages"],
    "token_budget": 350,
    "token_estimate": 124
  }
}
```

Targeted M4.5 smoke `3c7731d5-a31f-4adb-81f9-bd562fda2950`: scenario `prompt_memory_budget` на `gemma4:12b` и `qwen3.5:9b`, summary model `gemma4:12b`, `errors=0`, `prompt_memory_used=true`, `prompt_memory_budget_ok=true`, sources=5.

M4.5 stability check:

- 6 базовых M4.5 сценариев x 2 модели x 3 повтора = 36 результатов;
- модели: `gemma4:12b`, `qwen3.5:9b`;
- результат: `failed_flags=0`, `errors=0`;
- `summary_topic_switch` стабильно отключает prompt memory с `reason=topic_switch`;
- все сценарии с включённой memory остались в рамках `CONVERSATION_MEMORY_TOKEN_BUDGET=350`.

Большой M4.5 прогон для `qwen3.5:9b`:

- JSONL-артефакт: `research/m45_qwen35_big_evaluation_latest.jsonl`;
- 15 memory-сценариев x 7 повторов = 105 результатов;
- результат: `failed_count=0`, runtime errors = 0;
- средняя задержка около 5.18s;
- `prompt_memory.used=true`: 84 случая;
- `prompt_memory.used=false`: 21 случай, все с `reason=topic_switch`.

Итог по модели: `qwen3.5:9b` выбран как основной кандидат для дальнейших summary/context-memory и частых RAG regression прогонов. `gemma4:12b` остаётся эталонной моделью для сравнения и более осторожным summarizer baseline.

## M5.0: File Ingestion Skeleton

M5 начинается с production-minded document ingestion: сначала учимся принимать и индексировать простые файлы, но сразу добавляем metadata foundation для будущих buckets и tenant isolation.

Настройки по умолчанию:

```bash
DEFAULT_TENANT_ID=local_demo
DEFAULT_BUCKET_ID=taskflow_seed
```

M5.0 добавляет:

- загрузку `.txt`, `.md`, `.json` через общий `RawDocument` pipeline;
- `tenant_id`, `bucket_id`, `processing_status` на уровне документа и chunk;
- `tenant_id`, `bucket_id`, `processing_status`, `document_metadata` в Qdrant payload;
- compatibility с текущим seed ingestion: старые markdown/csv/yaml документы получают default bucket/tenant metadata.

Важно: `bucket_id` добавлен сразу как лёгкая metadata-рельса. Полноценный retrieval filter и no-leak evaluation между buckets остаются отдельным подэтапом M5 после базового PDF/document QA.

## M5.1: PDF Text Ingestion

M5.1 добавляет минимальную поддержку text-based PDF без OCR. PDF читается через `pypdf`, каждая страница становится отдельным `RawDocument`, чтобы source traceability могла ссылаться на конкретный `page_number`.

PDF metadata:

```json
{
  "source_type": "pdf",
  "document_metadata": {
    "file_name": "notifications_pdf_brief.pdf",
    "page_number": 1,
    "page_count": 1
  },
  "bucket_id": "taskflow_seed",
  "tenant_id": "local_demo"
}
```

Добавлен sample PDF:

```text
data/raw/tech_knowledge/notifications_pdf_brief.pdf
```

Evaluation:

- scenario: `pdf_text_ingestion`;
- request ограничивает `source_types=["pdf"]`;
- `score_threshold=0.0` для короткого synthetic PDF smoke;
- quality flags проверяют `has_pdf_source`, `pdf_page_metadata_ok`, `pdf_bucket_metadata_ok`, `pdf_mentions_notifications`.

M5.1 smoke `66901498-4411-4bf7-a159-758f3aba0603`: `pdf_text_ingestion` на `qwen3.5:9b`, sources=1, `failed_flags=0`.

M5.1 regression `aff5a8e9-8799-4a01-b398-d8b0aebc7a6d`: 5 baseline scenarios + `pdf_text_ingestion`, `failed_flags=0`, `errors=0`.

## M5.2: Document QA Evaluation

M5.2 начинает проверять не только факт ingestion, но и качество QA по документам: правильный тип источника, page metadata, bucket metadata, отсутствие смешивания нерелевантных PDF и latency разных моделей.

Для вопросов по конкретному документу `/rag/chat` поддерживает deterministic filters до LLM prompt:

```json
{
  "source_types": ["pdf"],
  "source_paths": ["/home/santera/Projects/data/raw/tech_knowledge/notifications_pdf_brief.pdf"],
  "document_ids": []
}
```

`source_paths` и `document_ids` фильтруются на уровне Qdrant payload. Это важно для будущего UI: если пользователь открыл конкретный файл или bucket, backend должен отобрать разрешённые chunks до передачи контекста в LLM.

Если задан `source_paths` или `document_ids`, backend не включает auto feature extraction из вопроса. Иначе продуктовые features вроде `projects` могут случайно отфильтровать chunks произвольного документа. Явно переданные `features` всё ещё применяются.

M5.2 synthetic PDF comparison `dc24ce47-e9e4-4755-9ed9-e9f987c8945b`:

- `qwen3.5:9b`: `pdf_text_ingestion`, sources=1, `failed_flags=0`, latency около 2.6s;
- `gemma4:12b`: sources=1, `failed_flags=0`, latency около 8.2s;
- `qwen3:14b`: sources=1, `failed_flags=0`, latency около 15.5s.

Локальный anonymized resume check не коммитит PDF и не сохраняет PII в документацию. Проверяются только категории extraction: страницы извлечены, контактные блоки распознаны как наличие данных, опыт/навыки/AI-LLM-RAG/CI-CD/security tooling находятся в тексте. После добавления `source_paths` filtered resume QA возвращает sources только из выбранного PDF.

## M5.3: Bucket Isolation

M5.3 добавляет первый access boundary для retrieval: `tenant_id` и `bucket_ids` фильтруются в Qdrant до сборки prompt. LLM получает только chunks из разрешённого tenant/bucket scope.

Пример `/rag/chat` request:

```json
{
  "message": "Что нужно сделать для Alpha enterprise clients по notifications?",
  "model": "qwen3.5:9b",
  "tenant_id": "local_demo",
  "bucket_ids": ["bucket_alpha"],
  "source_types": ["bucket_fixture"],
  "score_threshold": 0.0
}
```

Если `tenant_id` не передан, backend использует `DEFAULT_TENANT_ID`. Пустой `bucket_ids` означает все buckets внутри tenant. В production `tenant_id/bucket_ids` должны приходить из auth/session/access layer, а не напрямую от пользователя.

Для synthetic fixtures добавлен `data/raw/ingestion_manifest.json`: он назначает отдельным seed-файлам `tenant_id`, `bucket_id`, `source_type`, `features` и metadata, не индексируясь как обычный JSON-документ.

M5.3 smoke `af815661-b073-417d-91c1-b7d6a33a6934`:

- `bucket_alpha_positive`: sources=1, only `bucket_alpha`, `failed_flags=0`;
- `bucket_beta_positive`: sources=1, only `bucket_beta`, `failed_flags=0`;
- `bucket_no_leak_negative`: query asks about Alpha while scope is `bucket_beta`; sources only from `bucket_beta`, forbidden Alpha facts absent, `failed_flags=0`.

Важно: bucket сейчас - это логическая область/подборка документов. Полноценные `users`, `groups`, `roles`, `access_policies`, а также row-level/field-level permissions для таблиц остаются future hardening после upload/UI и structured table extraction.

## M5.4: Excel Row Ingestion

M5.4 добавляет baseline ingestion для `.xlsx` и `.xls`. Excel читается через `pandas` с engine dependencies `openpyxl` и `xlrd`. Каждая строка каждого sheet становится отдельным `RawDocument` с `source_type=excel_row`.

Для грязных Excel без нормальных headers loader добавляет в content компактную строку `Row values: ...`. Это сохраняет исходные `Unnamed:*` поля в metadata, но даёт LLM человекочитаемую строку таблицы.

Excel row metadata:

```json
{
  "source_type": "excel_row",
  "document_metadata": {
    "file_name": "product_owner_metrics.xlsx",
    "sheet_name": "Roadmap",
    "row_index": 0,
    "excel_row_number": 2
  },
  "bucket_id": "taskflow_seed",
  "tenant_id": "local_demo"
}
```

Добавлен synthetic fixture:

```text
data/raw/excel_fixtures/product_owner_metrics.xlsx
```

Evaluation:

- scenario: `excel_ingestion`;
- request ограничивает `source_types=["excel_row"]`;
- quality flags проверяют `has_excel_source`, `excel_sheet_metadata_ok`, `excel_row_metadata_ok`, `excel_bucket_metadata_ok`.

M5.4 smoke `fef54dac-ac00-4f49-b073-72ad40584920`: `excel_ingestion` на `qwen3.5:9b`, sources=5, `failed_flags=0`.

Локальный exploratory smoke на реальном `Price.xls`:

- файл не добавлен в git, но использован для проверки `.xls` ingestion;
- reindex после файла: 341 documents, 374 chunks;
- initial vector-only retrieval не находил точный barcode `4600682643425` и плохо отвечал на вопросы про шапку документа;
- добавлен deterministic Excel supplement внутри разрешённого scope: exact numeric terms для штрихкодов/артикулов и header rows для вопросов про документ/организацию/дату;
- final artifact: `research/m54_price_xls_model_smoke_latest.jsonl`;
- `qwen3.5:9b`: 6/6 сценариев, avg latency около 3.3s;
- `gemma4:12b`: 6/6 сценариев, avg latency около 7.9s.

Ограничение baseline: это row-level text ingestion, а не полноценный spreadsheet parser. Формулы, merged cells, pivot tables, rich formatting и cell-level permissions остаются future hardening.

## M5.4.1: Backend Hardening

M5.4.1 укрепляет backend перед DOCX/OCR этапами без большого переписывания проекта.

Что добавлено:

- `pytest` и первые unit tests для чистой логики;
- `create_app()` и FastAPI `lifespan` вместо deprecated startup event;
- reusable `OllamaClient` на одном `httpx.AsyncClient` с закрытием на shutdown;
- helper для fallback conversation context;
- часть RAG magic numbers/options вынесена в `Settings`;
- retrieval chain в `RagService` вынесен в отдельный private method.

Запуск unit tests:

```bash
cd /home/santera/Projects/backend
source .venv/bin/activate
PYTHONPATH=/home/santera/Projects/backend pytest -q
```

Проверки M5.4.1:

- unit tests: 13 passed;
- short RAG regression `7c445c79-c8f9-4cb3-93a4-38147eb25408`;
- scenarios: `general_po_summary`, `excel_ingestion`, `bucket_no_leak_negative`;
- result: 3/3 `ok`, `failed_flags=0`.

Осознанно отложено: CI/CD, Alembic, auth/RBAC, async Qdrant и dependency lock. К ним вернёмся перед upload/UI, OCR/load или public demo/deploy.

## M5.5: DOCX Ingestion

M5.5 добавляет baseline ingestion для `.docx` через `python-docx`. Legacy `.doc` сознательно не поддерживается: для baseline пользователь может конвертировать его в `.docx`, а полноценная поддержка старого формата остаётся future support.

DOCX читается как набор трассируемых блоков:

- обычные paragraphs становятся `RawDocument` с `source_type=docx`;
- строки таблиц тоже становятся `RawDocument` с `source_type=docx`;
- конкретный тип блока хранится в `document_metadata.block_type`: `paragraph` или `table_row`;
- `tenant_id` и `bucket_id` проходят тем же путём, что PDF/Excel/Markdown.

DOCX metadata:

```json
{
  "file_name": "product_owner_brief.docx",
  "block_type": "paragraph",
  "block_index": 3,
  "paragraph_index": 2
}
```

Для таблиц дополнительно сохраняются `table_index` и `table_row_index`, а content содержит `Row values: ...`, как в Excel baseline.

Добавлен sample DOCX:

```text
data/raw/docx_fixtures/product_owner_brief.docx
```

Evaluation:

- scenario: `docx_ingestion`;
- request ограничивает `source_types=["docx"]`;
- quality flags проверяют `has_docx_source`, `docx_block_metadata_ok`, `docx_table_or_paragraph_metadata_ok`, `docx_bucket_metadata_ok`;
- ответ должен найти risk и recommendation про enterprise onboarding handoff / Excel validation.

Проверки M5.5:

- unit tests: 14 passed;
- compile: `python -m compileall app scripts tests`;
- DOCX smoke `8c6436bb-f2ad-4a94-8707-b1505f758148`: `docx_ingestion`, sources=5, `failed_flags=0`;
- short regression `0f68ba39-72ad-4f54-8b8a-3ff984a619dc`: `general_po_summary`, `excel_ingestion`, `bucket_no_leak_negative`, `docx_ingestion`, `failed_flags=0`.

## M5.5.1: DOCX Chunking Hardening

Реальный технический DOCX `Front&Back_C#.docx` показал проблему baseline: многие задания и куски кода лежат в соседних paragraphs. Если индексировать каждый paragraph полностью отдельно, retrieval может найти описание задания, но не подтянуть следующую строку с кодом или сигнатурой.

Что изменено:

- точные `paragraph` и `table_row` blocks сохранены;
- paragraph content теперь включает короткий adjacent context: `Previous paragraph`, `Current paragraph`, `Next paragraph`;
- дополнительно создаются `paragraph_window` blocks с перекрытием;
- window metadata содержит `paragraph_start_index`, `paragraph_end_index`, `paragraph_count`, `window_index`;
- это лёгкий шаг к section-aware chunking без полноценного layout parser.

Проверки M5.5.1:

- unit tests: 14 passed;
- compile: `python -m compileall app scripts tests`;
- reindex после `Front&Back_C#.docx`: 679 documents, 712 chunks;
- `research/m55_frontback_docx_model_smoke_latest.jsonl`: 3 сценария x 3 модели = 9 результатов, `failed_flags=0`;
- модели: `qwen3.5:9b`, `gemma4:12b`, `qwen3:14b`;
- short regression `63e91ec7-7d5c-4825-8b4a-8b404e167db4`: `general_po_summary`, `excel_ingestion`, `bucket_no_leak_negative`, `docx_ingestion`, `failed_flags=0`.

## M5.5.2: DOCX Hybrid Retrieval / Reranking

M5.5.2 усиливает DOCX retrieval после baseline adjacent context. Теперь backend не только полагается на top-k vector search, но и deterministic путём добавляет локальный DOCX-контекст внутри уже разрешённого scope.

Что добавлено:

- `docx_supplement_scroll_limit` в `Settings`;
- `RagService` scroll-ит только `source_type=docx` внутри выбранных `tenant_id`, `bucket_ids`, `document_ids`, `source_paths`;
- exact/lexical supplement для code-like terms: `ModifyUsers`, `React`, `async`, `Task`, числовые маркеры;
- neighbor expansion по `paragraph_index` с радиусом 2;
- поддержка `paragraph_window` как широкого локального контекста;
- lightweight reranking: базовый vector score + exact match boost + небольшой `paragraph_window` boost;
- debug field `retrieval.docx_supplement_count`.

Важно: supplement не отправляет модель искать доступы. Access boundary остаётся прежним: backend сначала ограничивает scope, затем собирает локальный evidence bundle.

Проверки M5.5.2:

- unit tests: 17 passed;
- compile: `python -m compileall app scripts tests`;
- `research/m552_frontback_docx_hybrid_latest.jsonl`: 3 сценария x 3 модели = 9 результатов, `failed_flags=0`;
- `docx_supplement_count`: 12-14 на `Front&Back_C#.docx`;
- short regression `fc2604a2-230f-485a-9444-eb63d52e4dac`: `general_po_summary`, `excel_ingestion`, `bucket_no_leak_negative`, `docx_ingestion`, `failed_flags=0`.

## M5.6.1: Image OCR Baseline

M5.6 начинается с OCR-only baseline для изображений. Vision/caption digest остаётся следующим шагом: сначала извлекаем текст из `.png`, `.jpg`, `.jpeg`, сохраняем его как searchable evidence и прогоняем обычный RAG.

Системная зависимость:

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng
```

Python-зависимости:

```text
pillow
pytesseract
```

Image OCR loader:

- ищет `.png`, `.jpg`, `.jpeg` в `data/raw`;
- создаёт `RawDocument` с `source_type=image_ocr`;
- content содержит `File`, `Block type: image_ocr`, `OCR text`;
- metadata содержит `image_width`, `image_height`, `image_format`, `ocr_engine`, `ocr_languages`;
- `tenant_id` и `bucket_id` проходят тем же путём, что PDF/Excel/DOCX.

Если системный Tesseract не установлен, ingestion не падает: image OCR документы пропускаются с warning. Это позволяет backend работать без OCR, но для реального image smoke нужно установить системные пакеты.

Выбранные пользовательские fixtures:

- `data/raw/docx_fixtures/just_text.png` - чистый русский текст, основной OCR smoke;
- `data/raw/docx_fixtures/tablet.png` - таблица/коммерческое предложение, future table OCR smoke;
- `data/raw/docx_fixtures/charts.png` и `diagram.jpeg` - будущий chart/vision digest;
- `image.png` и `zabbix.jpg` больше подходят для M5.6.2 Vision Digest.

Проверки M5.6.1:

- unit tests: 18 passed;
- compile: `python -m compileall app scripts tests`;
- real OCR loader smoke: 6 `image_ocr` documents;
- reindex: 685 documents, 718 chunks;
- `image_ocr_ingestion` smoke `4132007a-f610-423e-9f3a-4844525d9c31`: sources=1, `failed_flags=0`;
- short regression `a7801121-cb2a-4278-950c-3b99f6dadb8b`: `general_po_summary`, `excel_ingestion`, `bucket_no_leak_negative`, `docx_ingestion`, `image_ocr_ingestion`, `failed_flags=0`.

## M5.6.2: Image Vision Digest

M5.6.2 добавляет второй слой для изображений: vision-модель создаёт compact digest/caption, а backend индексирует его как обычный text evidence. Это нужно для фото, графиков, диаграмм и monitoring screenshots, где OCR видит мало или видит шум.

Настройки:

```text
IMAGE_VISION_ENABLED=true
IMAGE_VISION_MODEL=gemma4:12b
```

Image digest:

- создаётся во время `scripts.ingest_seed_data`;
- использует Ollama `/api/generate` с `images`;
- перед отправкой нормализует изображение в PNG через Pillow, поэтому ошибочное расширение файла не должно ломать vision call;
- создаёт `RawDocument` с `source_type=image_digest`;
- content содержит `File`, `Block type: image_digest`, `Vision digest`;
- metadata содержит размеры, формат, `vision_model`, `digest_type=vision_caption`;
- исходная картинка не попадает в prompt ответа, туда попадает только digest text.

Targeted image digest:

- создаётся on-demand в `/rag/chat`, когда пользователь просит повторно проанализировать изображение или уточняет визуальный признак вроде цвета, формы или положения;
- слово «материалов» в смете не считается таким признаком: это подстрока маркера «материал», и раньше вопрос про смету уводил чат в live vision по чужим картинкам бакета;
- если в запросе задан `source_paths`, live vision не подменяет этот pin другими изображениями бакета;
- работает только для уже доступных пользователю image documents из narrow scope (`document_ids` attachments или выбранный bucket), а не по произвольному path из запроса;
- сохраняется в Qdrant как `source_type=image_targeted_digest` с deterministic point id по `document_id`, `bucket_id`, вопросу и `vision_model`;
- content содержит `File`, `Block type: image_targeted_digest`, `Focused question`, `Targeted vision digest`;
- metadata сохраняет `document_id`, `bucket_id`, `source_path`, `prompt_question`, `vision_model`, размеры изображения и `digest_type=targeted_visual_answer`;
- новый chunk сразу добавляется в текущий RAG prompt и остаётся доступным для будущих похожих вопросов.

Проверки M5.6.2:

- `gemma4:12b` подтвердил vision input через Ollama;
- unit tests: 20 passed;
- compile: `python -m compileall app scripts tests`;
- reindex: 690 documents, 723 chunks;
- after image normalization: 691 documents, 724 chunks;
- `image_digest` sources: 6;
- `image_digest_ingestion` smoke `43a7e78b-743b-47c9-b606-ed4cc7adce78`: sources=1, `failed_flags=0`;
- final short regression `a21a3e9e-00f3-44b0-b494-be338cdb79fa`: `general_po_summary`, `excel_ingestion`, `bucket_no_leak_negative`, `docx_ingestion`, `image_ocr_ingestion`, `image_digest_ingestion`, `failed_flags=0`.
- evaluator теперь поддерживает `required_numeric_values`: суммы вроде `1 416 960,00`, `1416960`, `1,416,960.00`, `1.416.960` нормализуются перед сравнением.
- evaluator также поддерживает `required_marker_groups`: для семантически одинаковых формулировок можно задать варианты вроде `("провер", "валидац", "validation")`;
- three-model smoke `78b0e70f-3a04-4d75-9910-78baa54d2672`: `qwen3.5:9b`, `gemma4:12b`, `qwen3:14b` прошли 10/10 сценариев, artifact `research/m56_three_model_10_scenario_latest.jsonl`.

Важно: `charts.png` оказался WEBP-like файлом с расширением `.png`. Это частый пользовательский сценарий, поэтому vision digest нормализует изображение в настоящий PNG перед отправкой модели.

Quality note: на `image.png` модель `gemma4:12b` прочитала крупную надпись как `UEFA`, хотя визуально ожидается `UFA`. Поэтому стабильный vision smoke использует `tablet.png`, а точное чтение текста на фото остаётся задачей OCR/vision reconciliation.

## M5.7: Complex Office Files

M5.7 расширяет Office ingestion за пределы простых строк и paragraphs:

- DOCX embedded images извлекаются из `word/media/*` и становятся `image_ocr` / `image_digest` evidence с `parent_source_type=docx`;
- XLSX embedded images извлекаются из `xl/media/*` и становятся `image_ocr` / `image_digest` evidence с `parent_source_type=xlsx`;
- native Excel charts становятся `excel_chart` evidence через `openpyxl` chart objects;
- если chart object не распознан openpyxl, loader использует fallback по `xl/charts/chart*.xml` и добавляет visible workbook context.

M5.7 metadata:

```json
{
  "block_type": "image_digest",
  "parent_source_type": "docx",
  "embedded_path": "word/media/image1.jpg",
  "embedded_image_index": 1
}
```

```json
{
  "block_type": "excel_chart",
  "chart_type": "clusteredColumn, paretoLine",
  "chart_xml_path": "xl/charts/chartEx1.xml"
}
```

Проверки M5.7:

- unit tests: 28 passed;
- reindex: 1012 documents, 1057 chunks;
- `docx_embedded_image_digest`, `excel_embedded_image_digest`, `excel_chart_pareto_ingestion`, `excel_native_chart_ingestion`;
- three-model smoke `c59e112c-aa33-472c-a15e-55f15a066428`: `qwen3.5:9b`, `gemma4:12b`, `qwen3:14b` прошли 4/4 сценария;
- artifact: `research/m57_complex_office_three_model_latest.jsonl`.

Quality note: `sample-with-images.docx` намеренно содержит рассинхрон - текст документа описывает gradient image, а embedded image фактически является графиком прибыли. Ingestion корректно разделяет эти evidence layers: `docx` text остаётся текстом документа, а `image_digest` / `image_ocr` описывают фактическое содержимое картинки.

## M5.7.5: Text vs Visual Evidence Mismatch

M5.7.5 добавляет первый scenario на сравнение разных evidence layers внутри одного Office-документа. Если запрос явно ограничен конкретным `source_path` и просит несколько `source_types`, retrieval supplement поднимает недостающие source types в первые `top_k`, чтобы модель получила и текст документа, и visual evidence.

Проверяемый кейс:

- `docx` paragraphs в `sample-with-images.docx` описывают gradient image;
- `image_ocr` и `image_digest` по embedded image показывают график прибыли;
- ответ должен сказать, что описание и фактическая картинка не совпадают.

Проверки M5.7.5:

- focused tests: 13 passed;
- `docx_text_image_mismatch` three-model smoke `9bde5707-a50c-4dc7-b250-4b50e739b103`;
- `qwen3.5:9b`, `gemma4:12b`, `qwen3:14b` прошли scenario без failed flags;
- artifact: `research/m575_docx_text_image_mismatch_latest.jsonl`.

## M5.7.6: Office Media Consistency Evidence

M5.7.6 переносит проверку согласованности Office media на ingestion layer. Backend создаёт отдельный `RawDocument` с `source_type=office_media_consistency`, который объединяет:

- текстовое evidence документа (`docx`, `excel_row`, `excel_chart`);
- `image_digest` по embedded image;
- `image_ocr`, если OCR доступен.

Baseline пока deterministic: если текст документа говорит про gradient image, а visual evidence говорит про график/прибыль, document получает `consistency_status=potential_mismatch`. Для остальных случаев ставится `review_needed`.

Metadata:

```json
{
  "block_type": "office_media_consistency",
  "parent_source_type": "docx",
  "embedded_path": "word/media/image1.jpg",
  "embedded_image_index": 1,
  "consistency_status": "potential_mismatch"
}
```

Проверки M5.7.6:

- unit tests: 30 passed;
- reindex: 1014 documents, 1061 chunks;
- `office_media_consistency_mismatch` three-model smoke `ebf63ad4-3b31-4ae0-a259-20579fc3744f`;
- `qwen3.5:9b`, `gemma4:12b`, `qwen3:14b` прошли scenario без failed flags;
- artifact: `research/m576_office_media_consistency_latest.jsonl`.

## M5.8: Legacy/Hard Excel Edge Cases

M5.8 закрывает первый real-world `.xls` edge case на `hard_for_analis.xls`. Файл является legacy OLE/BIFF Excel: `pandas/xlrd` достаёт табличные строки, но embedded images не отдаёт как структурированные Office media.

Что добавлено:

- `.xls` embedded images извлекаются lightweight fallback-ом по валидным JPEG/PNG binary blobs;
- повреждённые image blobs отсекаются полным чтением через Pillow;
- найденные картинки индексируются как обычные embedded image evidence: `image_ocr` и `image_digest`;
- metadata сохраняет `parent_source_type=xls`, `embedded_path=legacy-binary/imageN.jpg|png`, `embedded_image_index`;
- Excel retrieval supplement теперь учитывает не только длинные numeric identifiers, но и значимые lexical terms из вопроса, чтобы product-name queries попадали в нужную row.

Вывод по архитектуре: отдельный LibreOffice/headless fallback пока не нужен для baseline. Для текущего M5 достаточно явно поддержать `.xls` rows через `pandas/xlrd`, а embedded images доставать lightweight extractor-ом с честной metadata-пометкой `legacy-binary`.

Проверки M5.8:

- `hard_for_analis.xls`: 1 лист, 140+ строк, 27 полностью читаемых embedded images;
- unit tests: 21 passed для M5.8-related helpers;
- reindex: 1073 documents, 1145 chunks;
- `legacy_xls_text_ingestion` и `legacy_xls_embedded_image_digest` three-model smoke `1232422c-65b0-4e20-9660-7b65d95f04be`;
- `qwen3.5:9b`, `gemma4:12b`, `qwen3:14b` прошли оба scenario без failed flags;
- artifact: `research/m58_legacy_hard_excel_latest.jsonl`.

## M5.8.1: DOCX/XLSX Image Anchor Metadata

M5.8.1 добавляет связь embedded images с локальным Office-контекстом. Теперь картинка не просто принадлежит файлу, а может быть связана с конкретной DOCX table cell или XLSX anchor cell/row.

Что добавлено:

- DOCX image anchors извлекаются из `word/document.xml` + `word/_rels/document.xml.rels`;
- для картинок внутри DOCX table cells сохраняются `table_index`, `table_row_index`, `table_cell_index`, `table_row_text`;
- для картинок в DOCX paragraphs сохраняется `paragraph_index`, `paragraph_text` и ближайший previous paragraph fallback;
- XLSX image anchors берутся из `openpyxl` worksheet images;
- для XLSX сохраняются `sheet_name`, `anchor_row`, `anchor_col`, `anchor_cell`, `nearby_row_text`;
- общий ключ `linked_text` попадает и в metadata, и в `image_ocr`/`image_digest` content, чтобы retrieval мог найти картинку по тексту товарной строки.

Пример metadata:

```json
{
  "parent_source_type": "xlsx",
  "embedded_path": "xl/media/anchored_image5.png",
  "anchor_type": "xlsx_cell",
  "sheet_name": "Прайс с 01.05",
  "anchor_cell": "B11",
  "linked_text": "ПЯТНИЦКОЕ НЕФИЛЬТРОВАННОЕ ... Цена за кегу 3500 р."
}
```

Проверки M5.8.1:

- `sample-with-table 2.docx`: 5 embedded images linked to product table rows;
- `hard_for_analis_2.xlsx`: 75 images with `openpyxl` anchors, including `B11`/`E11` for the row with `4,1 %` and `3500 р`;
- reindex: 1423 documents, 1614 chunks;
- `docx_table_image_anchor_digest` и `xlsx_row_image_anchor_digest` three-model smoke `ffb874c7-ba06-4d3b-a437-275df3928a6b`;
- `qwen3.5:9b`, `gemma4:12b`, `qwen3:14b` прошли оба scenario без failed flags;
- artifact: `research/m581_office_image_anchor_latest.jsonl`.

Future hardening:

- legacy `.xls` layout linking остаётся отдельным экспериментом: нужен LibreOffice/headless conversion или BIFF/Escher parser, если понадобятся координаты картинок/shapes/OLE objects;
- field-level access/redaction для таблиц нужно делать до prompt: например, обычный пользователь видит `Name` и `Params`, но `Price` заменяется на `[REDACTED]`; LLM не должен решать доступы самостоятельно.

## M5.8.2: Scanned Table Layout OCR Baseline

M5.8.2 добавляет первый baseline для сканов/скриншотов таблиц, где структуры DOCX/XLSX уже нет и всё представлено пикселями.

Что добавлено:

- grid-like table detection без новой тяжёлой зависимости: через Pillow анализируются длинные горизонтальные/вертикальные линии;
- таблица разбивается на строки и ячейки по найденной сетке;
- последняя колонка рассматривается как image cell baseline;
- строка таблицы OCR-ится через Tesseract, чтобы получить `linked_text`;
- image cell вырезается как crop и индексируется через существующие `image_ocr` / `image_digest`;
- metadata содержит `parent_source_type=scanned_table`, `anchor_type=scanned_table_cell`, `table_row_index`, `table_cell_index`, `table_row_bbox`, `image_cell_bbox`, `linked_text`.

Ограничения baseline:

- рассчитан на хорошие сканы/скриншоты с видимой табличной сеткой;
- пока предполагает, что картинка находится в последней колонке;
- OCR linked text может быть шумным, особенно на маленьком/смазанном тексте;
- сложные layout cases без линий таблицы оставлены на следующий research layer.

Проверки M5.8.2:

- fixture: `data/raw/scanned_fixtures/scanned-table-products.png`;
- reindex: 1440 documents, 1629 chunks;
- `scanned_table_image_anchor_digest` three-model smoke `86d7cdf3-4a8a-4d26-b653-f6970715b83d`;
- `qwen3.5:9b`, `gemma4:12b`, `qwen3:14b` прошли scenario без failed flags;
- artifact: `research/m582_scanned_table_layout_ocr_latest.jsonl`.

Next research spike:

- PaddleOCR PP-Structure для table/layout parsing;
- docTR как OCR/document understanding кандидат;
- layoutparser и table detection models для сложных layouts;
- Donut/LayoutLM/Florence-like модели позже, когда baseline покажет реальные точки отказа.

## M5.8.3: PaddleOCR PP-Structure Spike Harness

M5.8.3 начинает “взрослый” OCR/layout spike без риска сломать основной backend. PaddleOCR не добавлен в обязательные зависимости: вместо этого есть optional script, который либо запускает PP-Structure, либо сохраняет compatibility finding.

Script:

```bash
PYTHONPATH=. ../.venv-paddleocr/bin/python scripts/spike_paddleocr_structure.py
```

Что делает script:

- проверяет наличие `paddleocr` и `paddle`;
- запускает `PPStructureV3`/legacy `PPStructure` на `data/raw/scanned_fixtures/scanned-table-products.png`, если зависимости доступны;
- сохраняет JSON artifact в `research/m583_paddleocr_structure_spike_latest.json`;
- если зависимостей нет, сохраняет `status=missing_dependency` и install hint.

Текущий результат:

- backend venv: Python 3.14.4, без PaddleOCR hard dependency;
- working spike venv: Python 3.11.15, `paddleocr==3.7.0`, `paddlex==3.7.2`, `paddlex[ocr]`, `paddlepaddle==3.2.2`;
- artifact: `research/m583_paddleocr_structure_spike_latest.json`;
- status: `completed`;
- PPStructureV3 нашёл `table` block, 7 layout boxes и HTML таблицы с image references.

Compatibility note: PaddlePaddle wheels могут отставать от новых версий Python. Если установка в текущий backend venv не пройдёт, лучше сделать отдельное spike-окружение на Python 3.10/3.11 и запускать PaddleOCR там, не смешивая тяжёлые зависимости с основным backend. Для PaddleOCR 3.7 полного `paddleocr` недостаточно для PPStructureV3: нужен `paddlex[ocr]`. `paddlepaddle==3.3.1` на CPU может падать с oneDNN/PIR ошибкой `ConvertPirAttribute2RuntimeAttribute not support`; в spike окружении рабочим оказался downgrade до `paddlepaddle==3.2.2`.

Дальше:

- сравнить PPStructureV3 output с M5.8.2 baseline;
- решить, как нормализовать HTML/image refs в `linked_text` evidence;
- оценить runtime, размер зависимостей и пригодность для production ingestion.

Итоговое решение по scanned OCR strategy зафиксировано в `research/SCANNED_OCR_STRATEGY.md`: текущий M5 production path остаётся на lightweight baseline, PaddleOCR остаётся optional advanced path/future hardening.

## E1 Auth: Service JWT From BFF

С E1 backend больше **не доверяет** browser headers `X-Tenant-ID` / `X-User-ID` / `X-User-Roles`.

Identity приходит только из signed BFF service JWT:

```bash
Authorization: Bearer <service-jwt>
```

Claims: `sub`, `tenant_id`, `roles`, `iss=taskflow-bff`, `aud=taskflow-backend` (HS256, shared `SERVICE_JWT_SECRET`).

`/rag/chat` дополнительно пересекает `document_ids` / bucket scope с `can_read_document` **до** Qdrant retrieval. Пустой scope без bucket резолвится в indexed available documents пользователя, а не во весь tenant corpus.

Для local curl без BFF можно выписать token так:

```bash
cd backend && source .venv/bin/activate
python - <<'PY'
from app.core.config import get_settings
from app.services.service_jwt import issue_service_jwt
s = get_settings()
print(issue_service_jwt(
    sub="local-user-1",
    tenant_id=s.default_tenant_id,
    roles=["admin"],
    secret=s.service_jwt_secret,
    issuer=s.service_jwt_issuer,
    audience=s.service_jwt_audience,
))
PY
```

Health endpoints (`/health/*`) остаются публичными. Product UI ходит через BFF (`:8001`) с httpOnly session cookie.

## E3.1 Tools Foundation

Controlled tools layer (перед agent chat UI в E3.3):

- `app/services/tools/` — registry, executor, role matrix, `ToolResult` (`ok|denied|invalid_input|failed`)
- Read tools: `get_user_context`, `list_buckets`, `get_document_status`, `rag_search`
- `get_document_status` принимает `document_id` **или** `file_name` (ACL через `list_available_documents`)
- `rag_search` scopes via `resolve_rag_document_ids` then `RagService.search` (retrieve-only, без generation)
- Audit: `metadata.tool_calls[]` shape + table `tool_call_logs` (Alembic `20260714_0007`)
- Portable JSON parse helper: `app/services/agent/tool_loop.py`

Role matrix: read tools — any authenticated; SQL tools (`text_to_sql`, `execute_readonly_sql`) — analyst/admin (E3.2).

```bash
cd backend && source .venv/bin/activate
pytest tests/test_tools_foundation.py -q
alembic upgrade head
```

## E3.2 Text-to-SQL Tools

Readonly SQL path for agents:

- `SqlExecutionService` — validate (`sql_validator` + allowlist) → `asyncpg` readonly transaction + row limit wrap
- `TextToSqlService` — schema card + LLM generate; preferred model `TEXT_TO_SQL_MODEL` (LoRA Ollama tag) with fallback `TEXT_TO_SQL_FALLBACK_MODEL`
- Tools: `text_to_sql` (generate+validate), `execute_readonly_sql` (validate+execute)
- Allowlist: analytics tables only (`sql_schema_card.DEFAULT_SQL_TOOL_ALLOWED_TABLES`); override via `SQL_TOOL_ALLOWED_TABLES`

Config keys: `SQL_TOOL_ENABLED`, `SQL_TOOL_ROW_LIMIT`, `SQL_TOOL_TIMEOUT_SECONDS`, `TEXT_TO_SQL_MODEL`, `TEXT_TO_SQL_FALLBACK_MODEL`.

```bash
pytest tests/test_sql_tools.py -q
```

Если Ollama tag для LoRA отсутствует — `TextToSqlService` делает fallback на `qwen2.5-coder:7b` + warning в tool result. Как создать tag — см. E3.4 ниже.

## E3.3 Agent Chat And Tool Trace

- `POST /agent/chat` — thin router + `AgentOrchestrator` (portable JSON tool loop)
- Memory (`prompt_memory`) входит в agent prompt, не в tools
- UI scope (`active_bucket_id` / `bucket_ids` / `document_ids`) прокидывается в tools via `extras`
- Tools: + `list_bucket_documents`, + `analyze_image` (vision digest)
- Response: `response`, `tool_calls[]`, `sources[]`, `steps`
- Frontend: режим **Agent** в TopBar; правая панель Tool trace

```bash
pytest tests/test_agent_orchestrator.py tests/test_agent_scope_tools.py tests/test_analyze_image_tool.py -q
# UI: Режим → Agent → «какие файлы в бакете?» / «что на картинке?»
```

## E6 Lab: LangGraph Adapter (beside handwritten Agent)

Статус: **lab closed**. Product default — `AgentOrchestrator` (`AGENT_LANGGRAPH_ENABLED=false`). LangGraph adapter оставлен как opt-in/учебный путь: шаги агента линейные и короткие, граф сейчас не нужен.

```bash
export AGENT_LANGGRAPH_ENABLED=true
# restart API → same POST /agent/chat / UI Agent mode
```

- `LangGraphAgentAdapter` — StateGraph (`call_model` → `execute_tools` → `finalize`) поверх тех же tools/RBAC/prompt;
- response `provider=langgraph`; chat metadata `agent_runtime=langgraph|handwritten`;
- metrics label `agent_runtime` (Grafana TaskFlow Overview); smoke `research/e6_runtime_grafana_smoke.json`.

```bash
pytest tests/test_agent_orchestrator.py tests/test_langgraph_adapter.py tests/test_metrics.py -q
```

## E3.4 Package V5 LoRA → Ollama Tag

PEFT safetensors для Qwen **не** подходят как Ollama `ADAPTER` напрямую. Рабочий путь: **adapter GGUF** (`llama.cpp convert_lora_to_gguf.py`) + Modelfile `FROM qwen2.5-coder:7b` + `ADAPTER …lora.gguf`. Полный merge (`--mode merge_full`) — тяжёлый fallback.

```bash
# one-time packing venv (CPU torch + peft/transformers/gguf)
cd backend
python3 -m venv .venv-lora-pack
.venv-lora-pack/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv-lora-pack/bin/pip install peft transformers gguf sentencepiece protobuf

# llama.cpp converters (example path)
# git clone https://github.com/ggerganov/llama.cpp /tmp/llama.cpp

.venv-lora-pack/bin/python scripts/package_text_to_sql_lora_ollama.py \
  --adapter-dir ../models/text_to_sql_lora/qwen2_5_coder_7b_v5_projection_steps400 \
  --llama-cpp-dir /tmp/llama.cpp \
  --mode adapter_gguf \
  --ollama-create
```

Артефакты пишутся в `models/text_to_sql_lora/..._ollama/` (каталог `/models/` в `.gitignore`). После `ollama create` tag `qwen2_5_coder_7b_v5_projection_steps400` должен появиться в `ollama list`.

## E4.1: n8n Disk Ingest + External DB Sync

Статус: **implemented (MVP)**.

Inbound seam (service JWT):

- `POST /integrations/ingest` — binary body + `X-File-Name` → stage/commit в bucket `n8n Integrations` (или `X-Bucket-Id` / `X-Bucket-Name`), metadata `source=n8n`, `channel=disk|…`
- `POST /integrations/sync-external-db` — sync slice из synthetic external Postgres (`EXTERNAL_POSTGRES_DSN`, default `:5433`) → allowlisted `external_customers` / `external_support_tickets`
- SQL allowlist включает эти таблицы; Agent использует обычные `text_to_sql` / `execute_readonly_sql`

Локальный прогон:

```bash
# deps: research/E4_DEPENDENCIES.md (n8n :5678, postgres-external :5433)
cd backend
python scripts/seed_external_demo.py
python scripts/issue_integration_jwt.py > /tmp/taskflow_n8n.jwt
TOKEN=$(cat /tmp/taskflow_n8n.jwt)

curl -sS -X POST http://localhost:8000/integrations/ingest \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-File-Name: external_integrations_brief.txt" \
  -H "X-Integration-Channel: disk" \
  -H "Content-Type: text/plain" \
  --data-binary @../data/integrations/inbox/external_integrations_brief.txt | jq

curl -sS -X POST http://localhost:8000/integrations/sync-external-db \
  -H "Authorization: Bearer $TOKEN" | jq
```

Compose profile `e4`: `docker compose --profile e4 up -d postgres-external n8n` (если ещё не запущены через `docker run`). Workflow JSON: `data/integrations/n8n_workflow_e4_disk_and_db.json`. План: `.cursor/plans/e4_n8n_integrations.plan.md`.

Out of scope: email OAuth, Jira, прямой agent→foreign DB, Kafka.

## E5.1: Kafka / Redpanda Indexing Worker

Статус: **done**; **E5.x** добавляет lifecycle events.

- `KAFKA_ENABLED=false` (default) → `BackgroundTasks` как раньше
- `KAFKA_ENABLED=true` → API публикует `indexing.requested`, worker вызывает `DocumentIndexingService.process_jobs`
- E5.x: worker публикует `document.indexed` / `document.index_failed` в `KAFKA_DOCUMENT_EVENTS_TOPIC` (default `taskflow.document.events`)
- `QDRANT_CHECK_COMPATIBILITY=false` по умолчанию — без warning client 1.18 vs server 1.12
- Broker: Redpanda (`docker compose --profile e5 up -d redpanda`), host `localhost:19092`
- Worker: `python -m scripts.run_indexing_worker`
- Deps: [research/E5_DEPENDENCIES.md](../research/E5_DEPENDENCIES.md), roadmap: `.cursor/plans/e5x_e7_e6_roadmap.plan.md`

```bash
docker compose --profile e5 up -d redpanda
export KAFKA_ENABLED=true
export KAFKA_BOOTSTRAP_SERVERS=localhost:19092
# terminal A
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# terminal B
python -m scripts.run_indexing_worker
```

Postgres `document_indexing_jobs` остаётся source of truth. Redis по-прежнему для rate limits.

## E7 Slice: MinIO / S3 Uploads

Статус: **baseline**. Uploads идут через `ObjectStorage` adapter.

- `OBJECT_STORAGE_ENABLED=false` (default) → локальный `data/raw/uploads` (как раньше)
- `OBJECT_STORAGE_ENABLED=true` → MinIO/S3; `DocumentAsset.source_path` = `storage://{key}`
- Indexing/vision materialize объект во временный файл перед парсерами
- Compose: `docker compose --profile e7 up -d minio` (API `:9000`, console `:9001`)

```bash
docker compose --profile e7 up -d minio
export OBJECT_STORAGE_ENABLED=true
export OBJECT_STORAGE_ENDPOINT=http://localhost:9000
# restart API (+ indexing worker if Kafka path)
```

Seed corpus под `data/raw/*` остаётся на диске; object storage покрывает upload lifecycle.

## E7 Slice: Compose Deploy Profile + Health

Статус: **baseline**.

### Health

| Service | Live | Ready |
|---------|------|-------|
| API | `GET /health/live` | `GET /health/ready` (+ kafka/minio probes when enabled) |
| Indexing worker | `GET :8002/health/live` | `GET :8002/health/ready` |

### Deploy profile

Один профиль поднимает infra extras + API + worker (Ollama остаётся на хосте):

```bash
docker compose --profile deploy up -d --build
curl -s http://localhost:8000/health/live
curl -s http://localhost:8002/health/live
curl -s http://localhost:8000/health/ready | jq
```

Сервисы: `backend-api` (:8000), `indexing-worker` (:8002), плюс `redpanda` + `minio` (входят в profile `deploy`).

Локальная разработка без Docker API по-прежнему: `uvicorn` + `python -m scripts.run_indexing_worker`.

## E7 Slice: Minimal Metrics

Статус: **baseline** (без Grafana/Prometheus server — future hardening).

In-process counters/histograms, Prometheus text без внешней зависимости:

| Endpoint | Назначение |
|----------|------------|
| `GET /metrics` | Prometheus exposition |
| `GET /metrics/summary` | компактный JSON для smoke |

Ключевые series: `taskflow_http_*`, `taskflow_rag_*`, `taskflow_agent_*`, `taskflow_indexing_jobs_total`. Worker на `:8002` отдаёт те же `/metrics` (indexing counters своего процесса).

Agent series несут label `agent_runtime=handwritten|langgraph` (не `runtime` — тот уже занят Prometheus scrape label `host|compose`). Grafana dashboard **TaskFlow Overview** группирует Agent rate/p95 по `agent_runtime`.

```bash
curl -s http://localhost:8000/metrics/summary | jq
curl -s http://localhost:8000/metrics | head
# worker (если запущен):
curl -s http://localhost:8002/metrics/summary | jq
```

Выключается через `METRICS_ENABLED=false`.

## E7 Slice: Prometheus + Grafana (ops UI)

Статус: **baseline**.

Отдельный ops stack (не вкладка продукта):

```bash
docker compose --profile observability up -d
# UI: http://localhost:3000  (admin/admin; anonymous Viewer enabled for lab)
# Prometheus: http://localhost:9090
```

- scrape: `host.docker.internal:8000/8002` (локальный uvicorn/worker) и `backend-api` / `indexing-worker` (profile `deploy`);
- dashboard: **TaskFlow Overview** (HTTP, RAG, Agent, indexing);
- в product UI кнопка **Observability** только для роли `admin` → открывает Grafana (`VITE_GRAFANA_URL`, default `http://localhost:3000`).

Profile `observability` также входит в `deploy`. Product charts во внутреннем UI — later.

## Seed Corpus And E1 ACL

`scripts/ingest_seed_data.py` индексирует `data/raw` в Qdrant (`bucket_id=taskflow_seed`, path-based chunk ids). После E1 `/rag/chat` режет retrieval по доступным `document_assets`.

После seed ingest (или если eval даёт `sources=0` на известных fixtures) синхронизируйте registry:

```bash
PYTHONPATH=/home/santera/Projects/backend ./.venv/bin/python scripts/sync_seed_document_registry.py
```

RAG ACL scope: `document_id` (upload UUID) **или** `source_path` из allowlist (`allowed_source_paths`). Явный user `source_paths` остаётся AND-сужением.

## E0 UI Skeleton: Buckets And Document Registry API

Для первого product UI добавлен минимальный API слой для управления buckets и document registry.

> **E1 note:** примеры curl ниже с `X-Tenant-ID` / `X-User-ID` устарели как identity source. Замените их на `Authorization: Bearer <service-jwt>` (см. секцию E1 Auth выше). Metadata headers вроде `X-File-Name` по-прежнему валидны.

Endpoints:

```bash
curl -s http://localhost:8000/buckets \
  -H "X-Tenant-ID: local_demo" | jq
```

```bash
curl -s -X POST http://localhost:8000/buckets \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: local_demo" \
  -H "X-User-ID: local-user-1" \
  -d '{"name":"Demo bucket","description":"Documents for UI demo"}' | jq
```

```bash
curl -s http://localhost:8000/buckets/<BUCKET_ID>/documents \
  -H "X-Tenant-ID: local_demo" | jq
```

Скачивание исходного файла идёт через backend (ACL: документ должен быть в бакете и `can_read`). Один id — исходный файл; несколько — zip. UI: кнопка в строке и «Скачать документы» с пикером (выбрать все / снять один / zip).

```bash
curl -s -D - "http://localhost:8000/buckets/<BUCKET_ID>/documents/<DOCUMENT_ID>/download" \
  -H "Authorization: Bearer <service-jwt>" -o aurora-legal.md
```

Baseline upload пока принимает raw body, чтобы не вводить `python-multipart` в системное Python окружение:

```bash
curl -s -X POST http://localhost:8000/buckets/<BUCKET_ID>/documents/upload \
  -H "X-Tenant-ID: local_demo" \
  -H "X-File-Name: notes.txt" \
  -H "Content-Type: text/plain" \
  --data-binary @notes.txt | jq
```

```bash
curl -s http://localhost:8000/documents/<DOCUMENT_ID>/status \
  -H "X-Tenant-ID: local_demo" | jq
```

### E0.1 Document Library And Access Model

E0.1 меняет смысл document registry: документ теперь может существовать в личной/tenant библиотеке без привязки к bucket, а bucket хранит ссылку на доступный документ.

Новые таблицы:

- `document_assets` - системная библиотека документов;
- `bucket_documents` - many-to-many связь bucket/document;
- `document_acl_entries` - explicit ACL grants для будущего RBAC.

Базовое правило доступа:

- owner видит свой private документ;
- `admin` видит документы tenant;
- `tenant` visibility видна всем в tenant;
- `role` visibility видна пользователям с пересечением ролей;
- bucket membership сам по себе не выдаёт доступ.

Примеры:

```bash
curl -s http://localhost:8000/documents/available \
  -H "X-Tenant-ID: local_demo" \
  -H "X-User-ID: local-user-1" \
  -H "X-User-Roles: admin,analyst" | jq
```

```bash
curl -s -X POST http://localhost:8000/buckets/<BUCKET_ID>/documents/<DOCUMENT_ID> \
  -H "X-Tenant-ID: local_demo" \
  -H "X-User-ID: local-user-1" \
  -H "X-User-Roles: admin,analyst" | jq
```

```bash
curl -s -X POST http://localhost:8000/documents/upload \
  -H "X-Tenant-ID: local_demo" \
  -H "X-User-ID: local-user-1" \
  -H "X-Document-Visibility: private" \
  -H "X-File-Name: notes.txt" \
  -H "Content-Type: text/plain" \
  --data-binary @notes.txt | jq
```

### E0.2 Staged Upload And Indexing Baseline

Production-like upload flow теперь должен идти через staging и явный commit:

```bash
curl -s -X POST http://localhost:8000/documents/stage \
  -H "X-Tenant-ID: local_demo" \
  -H "X-User-ID: local-user-1" \
  -H "X-File-Name: notes.txt" \
  -H "Content-Type: text/plain" \
  --data-binary @notes.txt | jq
```

После review в UI staged upload сохраняется в bucket:

```bash
curl -s -X POST http://localhost:8000/buckets/<BUCKET_ID>/documents/-/commit \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: local_demo" \
  -H "X-User-ID: local-user-1" \
  -H "X-User-Roles: admin,analyst" \
  -d '{
    "staged_upload_ids": ["<STAGED_UPLOAD_ID>"],
    "existing_document_ids": [],
    "removed_document_ids": [],
    "visibility": "private",
    "allowed_roles": []
  }' | jq
```

Commit создаёт:

- `document_assets`;
- `bucket_documents`;
- `document_indexing_jobs`.

Если backend подключен к Ollama и Qdrant, background task сразу запускает indexing baseline:

```text
committed document
-> load_raw_documents
-> chunk_documents
-> Ollama embeddings
-> Qdrant upsert
-> document_assets.status=indexed
```

Если indexing падает, `document_assets.status=index_failed`, а `document_indexing_jobs.error` хранит причину. Эта job boundary позже может быть заменена Kafka worker'ом без изменения UI contract.

Что сохраняется:

- `tenant_id`;
- `bucket_id`;
- `document_id`;
- `source_type`;
- `source_path`;
- `status`;
- `size_bytes`;
- upload metadata.

Ограничение baseline: indexing запускается in-process через `BackgroundTasks`. Это достаточно для E0 UI flow, но для production его нужно вынести в durable worker/queue.

### E0.3 Chat RAG And History Baseline

UI chat подключён к `/rag/chat`, а история чатов теперь хранится в PostgreSQL.

Новые/актуальные endpoints:

```bash
curl -s http://localhost:8000/chat/sessions \
  -H "X-Tenant-ID: local_demo" \
  -H "X-User-ID: local-user-1" | jq
```

```bash
curl -s -X POST http://localhost:8000/chat/sessions \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: local_demo" \
  -H "X-User-ID: local-user-1" \
  -d '{"title":"Новый чат","active_bucket_id":null,"model_id":"qwen3.5:9b","approach":"hybrid"}' | jq
```

```bash
curl -s http://localhost:8000/chat/sessions/<SESSION_ID>/messages \
  -H "X-Tenant-ID: local_demo" \
  -H "X-User-ID: local-user-1" | jq
```

Dropdown context сохраняется отдельным session update:

```bash
curl -s -X PATCH http://localhost:8000/chat/sessions/<SESSION_ID> \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: local_demo" \
  -H "X-User-ID: local-user-1" \
  -d '{"active_bucket_id":"","model_id":"qwen3.5:9b","approach":"hybrid"}' | jq
```

`POST /rag/chat` продолжает возвращать `session_id`, `user_message_id`, `assistant_message_id`. Frontend использует это для восстановления истории после перезагрузки.

Если пользователь выбирает `Без bucket` или явно просит поиск `по всем доступным документам`, frontend передаёт indexed accessible `document_ids` из `/documents/available`. Это временный E0.3 baseline; после Keycloak/RBAC scope resolution должен переехать в backend.

Важно: после этого этапа нужно применить миграции:

```bash
cd backend
alembic upgrade head
```

## E2.1 Slice: ModelGateway (Ollama + Gemini/OpenRouter)

Статус: **done** (2026-09-16) — gateway + SalesComposer + `--suite sales-gold`. На **коротком** корпусе Ollama `3abc0b52-…` и Gemini `073408bd-…` оба 4/4. На **жирном** (22 md): Ollama gold `a6c47b20-…` **4/4**, catalog `ff6c4f43-…` **10/10**; Gemini fat-gold `e7af95dc-…` **4/4**. OpenRouter ключа нет. Geo/rate-limit skip остаётся валидным (free tier 20 req/day на `gemini-3.6-flash`).

Generation для `/chat` и `/rag/chat` идёт через `ModelGateway`. Embeddings, vision digest и conversation summary остаются на Ollama.

Подходы:

- `local_only` — только Ollama; id вроде `gemini-3.6-flash` даёт `model_unavailable`, а не уезжает в локальный runtime;
- `hybrid` — Ollama; облачный fallback **только** на `/rag/chat` и только если synthetic-guard прошёл (infra 429/5xx / overload / connect). `/chat` hybrid в облако не фоллбечит;
- `external` (алиас `openapi`) — Gemini или OpenRouter по каталогу id. `/agent/chat` в этом срезе отвечает `external_agent_not_supported`.

Guard: нет `metadata.synthetic === true` → cloud generation запрещён. Флаг `session_seen_non_synthetic` пишется в `chat_sessions.metadata_json` и живёт пока жива сессия. Текст summary не классифицируем. Вставленный пользователем текст не сканируется.

Ключи (пустые = не настроено, `/health` отдаёт `gemini_key_configured` / `openrouter_key_configured`, без ping):

```bash
GEMINI_API_KEY=
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
GEMINI_DEFAULT_MODEL=gemini-3.6-flash
OPENROUTER_API_KEY=
OPENROUTER_DEFAULT_MODEL=openai/gpt-4o-mini
```

Цены: `app/core/model_pricing.py`. Нет строки в таблице → `estimated_cost_usd=null`.

### Sales-демопетля (этап B)

Gold-путь — `/rag/chat` + `SalesComposer`, не agent. Если выбран только бакет `sales_northwind` или `sales_aurora`, backend резолвит `deal_code`, читает карточку из `demo_deals` своим SQL (`tenant_id` + `bucket_id` + код) и достаёт договор из Qdrant. `RagService` про сделки не знает.

`demo_deals` **не** входит в allowlist `execute_readonly_sql`. Agent по-прежнему ходит в `evaluation_runs` / `external_*`.

Корпус сейчас **22 markdown** (11 Northwind + 11 Aurora), плюс 30 SQL-карточек. Жирные файлы в `data/raw/sales_*` — источник истины. `python -m scripts.render_sales_demo_docs` дописывает манифест и создаёт файл **только если его ещё нет**; повторный render короткие Python-fallback'и поверх демо не кладёт. `SalesComposer` для sales-бакетов делает второй поиск по `{deal_code} {title}`, предпочитает файлы спрошенной сделки и перед вопросом повторяет факты карточки (`closing_instructions`): пожелание/ориентир в договоре не заменяют слой `deal_card`.

Поднять корпус (Postgres должен быть доступен). Из папки `backend`, через venv проекта — не системные `python`/`alembic`:

```bash
cd /home/santera/Projects/backend
source .venv/bin/activate
alembic upgrade head
python -m scripts.seed_demo_deals
python -m scripts.render_sales_demo_docs
python -m scripts.ingest_seed_data --recreate
python -m scripts.sync_seed_document_registry
```

Без `activate` тот же путь: `.venv/bin/alembic` и `.venv/bin/python`. Если вы уже в `~/Projects/backend`, `cd backend` больше не нужен.

`--recreate` пересобирает всю Qdrant-коллекцию, не только sales. После ingest в UI выбирайте бакет Northwind и спрашивайте канонический код, например `Сравни сумму карточки и договора по nw-104`.

Намеренный рассинхрон для золота: `nw-104` сумма карточки 1250000 vs договор 1180000; `au-207` даты закрытия; `nw-110` в карточке `signed`, письмо — черновик и не отправлено. Маркер no-leak кабинета Aurora: `Aurora Polar Rebate`.

Upload с клиента не может выставить `synthetic=true`. External на пользовательских файлах по-прежнему 403 — это guard.

Gold и каталог:

```bash
python -m scripts.run_rag_evaluation --suite sales-gold --approach local_only --models qwen3.5:9b --top-k 8
python -m scripts.run_rag_evaluation --suite sales-catalog --approach local_only --models qwen3.5:9b --top-k 8
```

Четыре gold: `nw-104` суммы, `au-207` даты, `nw-110` draft vs signed, no-leak `Aurora Polar Rebate` на Northwind (в ответе запрещён `777000`, не название программы — модель может честно сказать, что в контексте её нет). Skip по `model_unavailable` / нет ключа / `external_scope_not_synthetic` / `external_provider_unavailable` (в том числе Gemini `User location is not supported`) не делает `evaluation_status=failed`.

Жирный корпус (2026-09-16): после closing reminder Ollama gold `a6c47b20-2947-4f90-b003-168933017303` — 4/4; catalog `ff6c4f43-f234-4275-96d2-e7d05092953f` — 10/10; Gemini fat-gold `e7af95dc-ace4-486c-8332-fa30f3beef40` — 4/4. Диагностика слоями: сначала retrieval, затем внимание (карточка vs «ориентир» в договоре). Bare «ноябрь» как золото карточки не принимаем. Free tier `gemini-3.6-flash`: 20 generate/day на проект; 429 — skip, не failed.

## Таблица на картинке: OCR и digest рядом

Для PNG/JPG/JPEG upload больше не ждёт пустого OCR, чтобы записать `image_digest`. Оба слоя индексируются вместе. DOCX/XLSX по-прежнему не получают digest встроенных картинок на этом пути: у них уже есть текст файла.

Промпт digest: если на картинке таблица, одна компактная markdown-таблица; фото и график без таблицы остаются в ветке «3–8 предложений». Default vision-модель по-прежнему `gemma4:12b`.

Фикстура `data/raw/scanned_fixtures/smeta-materials-table.png`:

- Tesseract склеивает столбцы и теряет десятичную точку (`Итого: 4825`). Это ложный слой для ячеек.
- Детектор сетки дал 0 crops. Это не ложное срабатывание, сетку в этом срезе не меняли.
- `gemma4:12b` после нового промпта пишет одну таблицу: «Лента широкая» 5,5 / 9 м / 49,5 и итог 482,5.

Eval `qwen3.5:9b`, `source_paths` на эту фикстуру. Прогон `5d063b35-977b-42c7-b52e-d479fce6a822` был HTTP-ok, но `required_source_types_present=false`: маркер «материал» сработал внутри «материалов», и в контекст попали `image_targeted_digest` чужих загрузок, включая копию той же сметы. Цифры совпали случайно, слои фикстуры в ответ не входили.

После правки маркера и `sync_seed_document_registry` прогон `89237d20-7f02-49d6-acab-3e52f8679e75`: оба сценария, sources=2 (`image_digest` выше `image_ocr`), `required_source_types_present=true`, итог 482,5, строка широкой ленты 5,5 и 49,5, запрет 4825 и «широкая 138» не сработал. Это внимание при двух чанках одного файла, не проверка ranking в переполненном бакете. Lexical supplement не добавлялся.

One-off digest `tablet.png` на новом промпте по-прежнему содержит коммерческую таблицу и `1 416 960`. Старый digest этой картинки в Qdrant не переиндексировался. Полный `--recreate` не запускался. PaddleOCR в default не включался.

## Липкий файл в Agent-чате

Если в сессии есть вложения, ход ищет один активный файл. Это последний загруженный, пока в вопросе не назван другой. Имя файла переключает активный и дальше держится уже он. Слова темы сами файл не меняют.

Пока `document_ids` хода непустой, `text_to_sql` и `execute_readonly_sql` агенту не отдаются и отклоняются исполнителем. Иначе вопрос про таблицу на картинке уходит в аналитическую схему. Короткая форма `{"rag_search":{"query":"..."}}` считается вызовом `rag_search`, а не текстом ответа.

Живая проверка 2026-09-24, Agent, `qwen3.5:9b`: тайминг `advanced` 121.3 с в 22:03:30 и 22:08:08; после смены файла узкая лента 9 м; вопрос про `advanced` на смете остаётся на смете и говорит, что скорости там нет. Журнал: `research/LESSONS_LEARNED.md`, запись «Цепочка правок от сметы на картинке до липкого файла».

## Резюме HeadHunter при индексации

PDF, в котором есть хотя бы два диапазона «месяц год — месяц год», при загрузке режется на блоки мест работы. Блок переходит на следующую страницу до следующего такого диапазона, поэтому название компании и строка технологий остаются в одном куске. «Навыки» и «Обо мне» кладутся отдельно, с меткой `resume_section`. Другие PDF по-прежнему идут постранично.

Если вопрос называет организацию, поиск оставляет только её блок и не подмешивает навыки и другие места работы. Кусок для эмбеддинга не длиннее 2200 символов: `nomic-embed-text` с окном 2048 токена на блоке около 5600 символов отвечает 500. Уже загруженное резюме само не переложится, а повтор того же файла по хешу индексацию не запускает. Журнал: запись «Резюме HeadHunter: блок места работы».
