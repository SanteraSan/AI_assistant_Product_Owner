# TaskFlow AI

Учебный **RAG / agent** ассистент для Product Owner: локальные LLM, поиск по документам, оценка качества ответов и явные границы доступа.

Это не production-система и не «обёртка над ChatGPT». Цель проекта — пройти руками весь контур LLM-приложения и уметь объяснить, **на каком слое** ответ получился хорошим или плохим: ingestion, chunking, retrieval, prompt, модель, evaluator или agent/tools.

Репозиторий публичный: [SanteraSan/AI_assistant_Product_Owner](https://github.com/SanteraSan/AI_assistant_Product_Owner).

## Что умеет система

- Отвечает по документам с источниками, а не «из памяти модели».
- Держит доступ на backend **до** сборки промпта: модель не решает, что пользователю можно видеть.
- Индексирует разные представления одного файла: текст, страницы, Excel-строки, OCR, vision digest, native charts, consistency evidence.
- Ведёт чат с историей, summary и бюджетом контекста.
- Даёт agent-режим с tools (поиск, список buckets/файлов, read-only SQL, разбор картинки) и RBAC на исполнении tool.
- Сравнивает модели и регрессии через eval-сценарии, а не только глазами.
- Локально прогоняет QLoRA spike для Text-to-SQL и честно фиксирует, чего короткий fine-tune не даёт.

## Архитектура

```text
UI (React, тестовая оболочка)
  -> BFF (session + CSRF + service JWT)
    -> FastAPI
         -> RAG: retrieve (Qdrant) + ACL filters + prompt + Ollama
         -> Agent: handwritten orchestrator (default) / LangGraph lab
         -> Tools: rag_search, SQL, documents, vision
         -> Indexing worker (Redpanda/Kafka) -> embeddings -> Qdrant
    PostgreSQL: чаты, ACL, jobs, eval runs
    MinIO: файлы
    Keycloak: роли
```

Инженерные правила, с которыми собран проект:

- retrieved sources — evidence; память и summary — только context;
- несколько evidence layers лучше, чем один text blob;
- если качество просело, сначала диагностируется слой, а не «берём модель побольше»;
- eval не ослабляется вслепую: сначала смотрим, хрупкий marker это или реальная ошибка.

Подробности: [`Project_spec.md`](Project_spec.md), [`backend/README.md`](backend/README.md), [`research/LESSONS_LEARNED.md`](research/LESSONS_LEARNED.md).

## Стек

| Слой | Что используется |
| --- | --- |
| Inference | Ollama + optional Gemini/OpenRouter через OpenAI-compatible gateway |
| RAG | FastAPI, Qdrant, embeddings, metadata filters, hybrid retrieval / rerank для Office |
| Данные | PostgreSQL, Alembic, Redis |
| Ingestion | PDF, DOCX, XLSX, изображения, OCR, vision digest |
| Agent | самописный orchestrator + opt-in LangGraph adapter |
| Text-to-SQL | schema card, sqlglot guardrails, LoRA fallback |
| Auth | Keycloak, BFF, service JWT, tenant/bucket/document ACL |
| Ops lab | indexing worker, Redpanda, MinIO, Prometheus, Grafana |
| Frontend | React, TypeScript, Vite — экран для ручной проверки |
| Оценка | unit-тесты, RAG eval scenarios, three-model smoke, журнал в `research/` |

## Что важно для ревью

Проект разрабатывался как lab с AI-pair programming (Cursor). Это не скрывается: в коммитах есть `Co-authored-by: Cursor`.

Моя зона ответственности — постановка задачи, границы системы, разбор ошибок, eval и решения вроде:

- ACL и requested-file scope применяются до prompt construction;
- текст Office-файла и embedded image — разные evidence, даже если они противоречат друг другу;
- handwritten agent остаётся default: линейный tool-loop не требует графа;
- LangGraph оставлен как лабораторный adapter с теми же tools и RBAC;
- короткий QLoRA Text-to-SQL smoke улучшил синтаксис, но не дал semantic exact-match — это зафиксировано, а не замаскировано.

Фронтенд сделан, чтобы можно было руками проверить чат, загрузку и доступ. Это тестовая оболочка, не enterprise-пример: большого внимания ей не уделялось.

## Как смотреть код

Имеет смысл идти не «с первого коммита», а по слоям:

1. Retrieval и prompt: `backend/app/services/rag_service.py`, `backend/app/services/rag_scope.py`
2. Ingestion: `backend/app/services/document_loader.py`, `backend/app/services/chunking.py`
3. Agent / tools: `backend/app/services/agent/`, `backend/app/services/tools/`
4. Access: `backend/app/services/access_policy.py`, `bff/`
5. Оценка: `research/RAG_EVALUATION_CHECKLIST.md`, `backend/scripts/`
6. UI: `frontend/src/pages/chat/`, `frontend/src/widgets/`

Наблюдения и провалы экспериментов: [`research/LESSONS_LEARNED.md`](research/LESSONS_LEARNED.md).

## Запуск

Нужны Docker, локальный Ollama и Python 3.14 / Node из [`DEVELOPMENT.md`](DEVELOPMENT.md).

```bash
make bootstrap
docker compose up -d
make backend-migrate
make dev-backend
make dev-frontend
```

Полный контур (indexing worker, MinIO, Grafana, Keycloak) описан в [`backend/README.md`](backend/README.md). Это учебный baseline, не production hardening.

## Ограничения

- нет полноценного нагрузочного контура и cost/SLO;
- LoRA — spike, не прод-модель;
- legacy `.doc` / сложный chart rendering / layout-aware parsing специально оставлены как future hardening;
- часть enterprise-слоя (Kafka, MinIO, Grafana, LangGraph) сделана как лабораторный срез, а не как «мы уже банк»;
- фронтенд — экран для проверки бэкенда, а не отдельный продуктовый UI.

Это сознательный ритм проекта: маленький baseline → оценка → hardening → запись в журнал.
