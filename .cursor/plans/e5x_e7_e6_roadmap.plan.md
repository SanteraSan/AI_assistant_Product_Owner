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

## E7 slice

1. MinIO/S3 for uploads — **done**
2. Compose/deploy profile + worker/API health — **done**
3. Minimal metrics — **done** (`/metrics`, `/metrics/summary`)
4. Prometheus + Grafana ops UI + admin deep-link — **done**

Next: **E6 lab closed** — discuss next enterprise/hardening slice.

Defer: mega admin UI, audit export suite, full report generation, in-app product charts.

## E6 lab

Status: **closed (2026-07-15)** — lab done; product keeps handwritten Agent.

- thin LangGraph adapter calling existing tools/RBAC — **done**
- feature flag `AGENT_LANGGRAPH_ENABLED` (default **off**); handwritten Agent remains primary
- unit side-by-side parity tests — **done**
- live API smoke handwritten vs langgraph (`qwen3.5:9b`) — **done** (see `research/e6_handwritten_vs_langgraph_smoke.json`)
- Grafana split by `agent_runtime` label + 4-scenario smoke — **done** (`research/e6_runtime_grafana_smoke.json`)
- **Product decision:** do **not** switch default to LangGraph; linear few-step agent does not need graph complexity. Adapter stays as opt-in/educational path. No UI runtime toggle planned.

Next discussion: what comes after E5.x + E7 slice + E6 lab close (remaining enterprise backlog / hardening).

## Backlog: формат табличных данных для модели (TOON / CSV)

Status: **идея, не начато (2026-10-17)**. Обсуждено вместе с личным AI-стеком (`~/dev-ai-stack`): там формат ответов devmem делается сменным и проверяется бенчмарком. Здесь — то же для TaskFlow.

Контекст: TOON (Token-Oriented Object Notation) для однородного массива объектов пишет имена полей один раз в заголовке, дальше строки как в CSV. Авторы заявляют экономию 30–60% токенов против JSON на таких данных. Для локальных моделей с небольшим окном это заметно.

Кандидаты в коде:

- `backend/app/services/tools/execute_readonly_sql.py` — `tool_ok` отдаёт `rows` списком словарей. В JSON имена колонок повторяются в каждой строке. Самый сильный кандидат.
- `backend/app/services/loaders/excel.py`, `_worksheet_context` — уже компактно (`" | ".join`), но пустые ячейки выбрасываются, и значения сдвигаются относительно колонок. Табличный формат с заголовком и пустыми значениями на месте исправил бы и это. Отдельно проверить, влияет ли сдвиг на текущие Excel-сценарии.
- Строковые evidence-слои из Excel (row evidence) — проверить, как они сейчас попадают в промпт.

План:

1. Одна функция сериализации табличного результата с параметром `json | toon | csv | markdown`. По умолчанию — текущее поведение, чтобы не сломать существующие eval.
2. Unit-тесты: одинаковые данные во всех форматах, экранирование, пустые значения, усечение (`truncated`).
3. Eval-сценарии на SQL и Excel: входные токены (`usage.prompt_tokens`) и точность ответа по маркерам с нормализацией чисел. Модели: `qwen3.5:9b`, `gemma4:12b`, `qwen3:14b`.
4. Сравнивать TOON прежде всего с CSV и markdown, а не только с JSON: CSV экономит почти столько же, а модели знают его лучше.

Границы:

- протокол tool calling и структурированные ответы модели остаются JSON; модель не просят отвечать в TOON;
- формат меняется только после eval, а не по заявленным цифрам; если TOON не выигрывает у CSV — оставить CSV и записать вывод в `research/LESSONS_LEARNED.md`.
