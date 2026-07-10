# Backend Hardening Roadmap

Цель: укрепить backend перед `M7: LoRA Text-to-SQL Fine-Tuning` и `M8: Analytics UI, Dashboards And Reports`.

Этот блок не добавляет новую продуктовую фичу сам по себе. Он делает текущий FastAPI/PostgreSQL/Qdrant/Ollama backend более предсказуемым, наблюдаемым и безопасным для следующих этапов, где появятся SQL execution path, Redis, очереди и UI.

## Current Baseline

На текущем уровне backend уже имеет:

- `FastAPI` endpoints `/chat`, `/rag/chat`, `/health`;
- PostgreSQL через async SQLAlchemy;
- таблицы для chat history, RAG logs, conversation summaries и evaluation runs;
- Qdrant single collection `documents`;
- Ollama client для generation/embeddings;
- document ingestion и regression suite.

Основные ограничения текущего baseline:

- DB schema создаётся через `Base.metadata.create_all`;
- нет Alembic migration history;
- config values имеют defaults, но мало строгой validation;
- health endpoint смешивает liveness и readiness;
- error handling частично дублируется в endpoints;
- нет Redis-backed coordination layer;
- нет centralized request limits/backpressure для Ollama;
- heavy ingestion/OCR/vision work ещё не отделён job boundary;
- RBAC пока представлен bucket metadata foundation, но не полноценным request/user context layer.

## Hardening Principles

- Backend должен отказывать управляемо, а не зависать.
- LLM inference считается scarce resource: не отправлять burst requests напрямую в Ollama.
- Access filtering происходит до prompt.
- Любой execution path, особенно будущий SQL path, должен иметь validator, timeout и audit trail.
- Новые изменения закрываются focused tests/smoke checks, а рискованные изменения - targeted regression.
- CI/CD пока не входит в scope: локальные команды и documented runbooks важнее на текущем этапе.

## Stage H1: Alembic Migrations

Цель: заменить implicit schema evolution через `metadata.create_all` на явные миграции.

Задачи:

- добавить `alembic`;
- создать `backend/alembic.ini` и `backend/alembic/`;
- подключить `app.db.base.Base.metadata`;
- создать initial migration для текущих таблиц;
- оставить `create_all` только как local/dev fallback или убрать из startup после проверки миграций;
- задокументировать команды `alembic upgrade head` и `alembic current`.

Проверки:

- `alembic upgrade head` на пустой БД;
- backend `/health` после миграции;
- focused tests вокруг DB models/session;
- smoke evaluator на 1-3 сценария после migration path.

Definition of Done:

- новая БД поднимается через Alembic;
- текущие SQLAlchemy models соответствуют migration;
- journal содержит результат migration smoke.

## Stage H2: DB Constraints And Indexes

Цель: сделать DB слой более устойчивым и быстрым для logs/evaluation/history.

Задачи:

- проверить индексы для `chat_messages.session_id`, `created_at`;
- добавить индексы для `evaluation_results.run_id`, `scenario_id`, `model`;
- добавить индексы для `rag_request_logs.created_at`, `model`, `collection`;
- проверить foreign keys и cascade behavior;
- добавить уникальные ограничения только там, где есть явный invariant;
- подготовить future поля/indexes для `tenant_id`, `bucket_id`, `document_id`, если они будут перенесены из Qdrant metadata в PostgreSQL document registry.

Проверки:

- migration upgrade на существующей dev DB;
- простые SQL checks через Postgres;
- regression не нужен, если меняются только индексы/constraints без application behavior.

Definition of Done:

- DB constraints выражают реальные invariants;
- частые diagnostic queries имеют индексы;
- migration reversible или явно documented.

## Stage H3: Config Validation

Цель: backend должен падать на старте с понятной ошибкой, если критичная настройка некорректна.

Задачи:

- добавить Pydantic validators для URL/DSN/positive numeric limits;
- разделить defaults для local demo и required settings для strict mode;
- добавить settings для request/message/file limits;
- добавить settings для Redis/Ollama concurrency;
- добавить tests для valid/invalid config.

Проверки:

- unit tests для `Settings`;
- backend startup smoke;
- `/health` должен отражать выбранные модели и лимиты.

Definition of Done:

- invalid config не приводит к поздним runtime failures;
- ошибки старта объясняют, какую переменную исправить.

## Stage H4: Structured Logging And Request ID

Цель: каждый запрос должен быть трассируемым по логам и DB records.

Задачи:

- добавить middleware для `request_id`;
- принимать `X-Request-ID`, если он передан, иначе генерировать новый;
- возвращать `X-Request-ID` в response headers;
- добавить request_id в logs и response/debug metadata там, где уместно;
- подготовить structured log format для endpoint, model, latency, session_id, source_count, error_type.

Проверки:

- tests для middleware;
- smoke `/chat` и `/rag/chat` с custom `X-Request-ID`;
- убедиться, что request_id не раскрывает приватные данные.

Definition of Done:

- запрос можно проследить через response header, app logs и DB metadata.

## Stage H5: Error Handling Policy

Цель: унифицировать ошибки API и dependency failures.

Задачи:

- выделить typed application exceptions;
- добавить exception handlers для validation/dependency/model/ingestion errors;
- не возвращать raw provider tracebacks пользователю;
- логировать internal details с request_id;
- сохранить понятные user-facing messages.

Проверки:

- unit/API tests для Ollama unavailable, Qdrant not ready, invalid request;
- smoke with stopped dependency where practical.

Definition of Done:

- ошибки отличаются по категории и статус-коду;
- пользователю возвращается безопасная ошибка, а debug details остаются в логах.

## Stage H6: Request Validation And Limits

Цель: ограничить входные данные до того, как они попадут в expensive path.

Задачи:

- лимитировать длину `message`;
- лимитировать `top_k`, `candidate_multiplier`, списки filters/source paths/document ids;
- подготовить лимиты для future upload/audio/report endpoints;
- добавить timeout policy для generation, embeddings, OCR/vision digest, SQL execution;
- возвращать `413/422/429/503` в зависимости от причины отказа.

Проверки:

- API tests для boundary values;
- focused regression на `/rag/chat`, чтобы обычные запросы не сломались.

Definition of Done:

- expensive operations защищены от случайно огромных запросов;
- limits видны в config/docs.

## Stage H7: Auth/RBAC Foundation

Цель: подготовить deterministic access boundary до prompt.

Задачи:

- добавить lightweight request user context: `user_id`, `roles`, `tenant_id`;
- описать `allowed_bucket_ids` как backend-computed value;
- не давать модели решать доступы;
- использовать bucket filters перед retrieval;
- подготовить future redaction boundary для field-level restrictions.

Проверки:

- bucket positive/negative regression scenarios;
- tests, что unauthorized bucket не попадает в sources/prompt;
- audit metadata: кто запросил, какие bucket_ids разрешены.

Definition of Done:

- access boundary выражен в backend policy layer;
- prompt получает только разрешённые sources.

## Stage H8: Ingestion Idempotency And Status Model

Цель: сделать ingestion повторяемым и диагностируемым.

Задачи:

- ввести document registry concept для source files;
- статусы: `pending`, `processing`, `completed`, `failed`, `skipped`;
- хранить checksum/source_path/bucket/tenant/version metadata;
- повторная загрузка того же файла не должна плодить мусор без явного `--recreate`;
- фиксировать processing errors per document.

Проверки:

- ingest same file twice smoke;
- failed document не ломает весь batch;
- Qdrant chunk counts объяснимы после repeat ingestion.

Definition of Done:

- ingestion имеет audit trail и idempotency rule.

## Stage H9: Background Jobs For Heavy Work

Цель: отделить heavy tasks от request-response flow.

Задачи:

- выделить job model/interface;
- future job types: document ingestion, OCR, image digest, office media consistency, audio transcription, report generation;
- определить sync dev fallback и Redis-backed async mode;
- хранить job status/progress/error.

Проверки:

- unit tests для status transitions;
- smoke: job submitted -> completed/failed;
- no regression in current CLI ingestion.

Definition of Done:

- heavy work имеет job boundary и может быть вынесен в worker без переписывания бизнес-логики.

## Stage H10: Health And Readiness Diagnostics

Цель: отделить “process is alive” от “service can handle work”.

Endpoints:

- `/health/live`: process alive;
- `/health/ready`: Postgres, Qdrant, Redis, Ollama, embeddings, collection availability;
- `/health/models`: optional model availability/config snapshot.

Проверки:

- readiness показывает degraded dependency;
- liveness не делает дорогих dependency checks;
- existing `/health` либо остаётся backward-compatible, либо документированно переезжает.

Definition of Done:

- runbooks могут понять, что именно сломано: DB, Qdrant, Redis, Ollama, model, collection.

## Stage H11: Redis-Backed Queueing, Rate Limiting, And Ollama Concurrency Control

Цель: переживать burst traffic без обрушения Ollama/FastAPI.

Важно: цель не в том, чтобы одна локальная машина одновременно сгенерировала 1000 LLM-ответов. Цель - принять burst входящих запросов, ограничить concurrency, поставить backpressure и вернуть управляемый отказ при перегрузке.

Задачи:

- добавить Redis в `docker-compose`;
- добавить Redis client/service;
- добавить per-model concurrency limit;
- добавить lightweight queue или semaphore для Ollama generation;
- добавить rate limit на пользователя/session/IP для expensive endpoints;
- добавить overload response при переполненной очереди;
- добавить metrics/debug: queue depth, wait time, model concurrency, rejected count;
- подготовить local burst/load script на 1000 коротких запросов.

Проверки:

- unit tests для limiter/semaphore logic;
- smoke with Redis unavailable;
- local burst test: backend не падает, часть запросов проходит, перегрузка возвращает controlled `429/503`;
- targeted `/chat` и `/rag/chat` regression после integration.

Definition of Done:

- Ollama protected by backend concurrency policy;
- overload behavior documented and testable;
- Redis failure mode понятен.

## Suggested Commit Order

1. `docs: plan backend hardening roadmap`
2. `feat: add alembic migrations`
3. `feat: add database constraints and indexes`
4. `feat: harden config validation`
5. `feat: add request tracing and structured errors`
6. `feat: add request limits`
7. `feat: add access context foundation`
8. `feat: add ingestion status model`
9. `feat: add background job boundary`
10. `feat: split health and readiness checks`
11. `feat: add redis-backed ollama load protection`

## Regression Policy

- Docs-only hardening plan: no test run required.
- DB migrations/constraints: migration smoke + focused DB tests.
- Config/errors/limits: unit/API tests + small `/rag/chat` smoke.
- RBAC/access filtering: bucket isolation regression scenarios.
- Redis/Ollama protection: limiter tests + burst smoke + targeted chat/RAG regression.
- Before M7 starts: run a compact full backend regression to confirm the hardening block did not weaken M5 behavior.
