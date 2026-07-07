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

При старте backend автоматически создает минимальные таблицы, если PostgreSQL доступен:

- `rag_request_logs` - сообщение пользователя, ответ модели, latency, выбранная модель, retrieval/router/context policy параметры;
- `rag_source_logs` - sources, которые попали в ответ, включая score, title, source type, source path, metadata и короткий excerpt content.
- `chat_sessions` - логические диалоги пользователя;
- `chat_messages` - user/assistant сообщения внутри session.
- `conversation_summaries` - компактный rule-based summary длинных sessions для M4.3.

Логирование `/chat` и `/rag/chat` работает best-effort: если PostgreSQL временно недоступен, ответ все равно вернется, а ошибка попадет в backend logs. Полная история не подмешивается в prompt напрямую; conversation context слои M4 используют ее только для управляемого построения `retrieval_query`.

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
CONVERSATION_SUMMARY_MODEL=qwen2.5:3b
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
  "summary_model": "qwen2.5:3b",
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
