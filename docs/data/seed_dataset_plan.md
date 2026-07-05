# Seed Dataset Plan

Документ описывает минимальный набор данных для первого RAG-demo проекта `TaskFlow AI`.

Цель seed dataset - не объем, а связность. Данные должны позволять ассистенту отвечать на вопросы, которые требуют соединить:

- техническую документацию;
- support/user feedback;
- бизнес-метрики;
- release/incident notes;
- persona-specific контекст.

## Структура Каталогов

```text
data/
  raw/
    tech_knowledge/
    user_feedback/
    business_metrics/
    release_notes/
  seed/
```

## Минимальный Набор На M1

Для первого рабочего RAG достаточно:

| Тип | Количество | Формат | Коллекция |
| --- | --- | --- | --- |
| OpenAPI спецификация | 1 | YAML или JSON | `documents`, позже `tech_knowledge` |
| Технические документы | 5 | Markdown | `documents`, позже `tech_knowledge` |
| Product/RFC/ADR | 5 | Markdown | `documents`, позже `tech_knowledge` |
| Support tickets | 30 | CSV | `documents`, позже `user_feedback` |
| User reviews | 20 | CSV или JSONL | `documents`, позже `user_feedback` |
| Metrics reports | 3 | CSV | `documents`, позже `business_metrics` |
| Release/incident notes | 5 | Markdown | `documents`, позже `tech_knowledge` или отдельный domain |
| Test questions | 20-40 | JSONL | не векторизуем, используем для eval |

## Feature Coverage

Каждая ключевая фича должна присутствовать минимум в двух слоях данных.

| Feature | Tech Docs | Feedback | Metrics | Notes |
| --- | --- | --- | --- | --- |
| `notifications` | да | да | да | incident note |
| `csv_import` | да | да | да | RFC |
| `permissions` | да | да | да | ADR |
| `reports` | да | да | да | release note |
| `search` | да | да | желательно | incident note |
| `webhooks` | да | да | желательно | runbook |
| `integrations` | да | да | желательно | release note |
| `tasks` | да | желательно | да | product requirement |
| `projects` | да | желательно | да | product requirement |
| `sprints` | желательно | желательно | да | product requirement |

## Raw Data Files

### `data/raw/tech_knowledge/taskflow_openapi.yaml`

OpenAPI спецификация TaskFlow API.

Минимальные endpoint groups:

- `Tasks`;
- `Projects`;
- `Sprints`;
- `Notifications`;
- `CSV Import`;
- `Reports`;
- `Webhooks`;
- `Permissions`.

Примеры endpoint:

- `GET /api/v1/tasks`;
- `POST /api/v1/tasks`;
- `POST /api/v1/imports/csv`;
- `GET /api/v1/reports/sla`;
- `POST /api/v1/webhooks/retry`;
- `GET /api/v1/notifications/settings`;
- `PATCH /api/v1/projects/{project_id}/permissions`.

### `data/raw/tech_knowledge/notifications_architecture.md`

Содержит:

- как устроен notification service;
- какие каналы поддерживаются;
- retry policy;
- rate limits;
- типовые ошибки;
- связь со Slack/Telegram/email.

Features:

- `notifications`;
- `integrations`;
- `webhooks`.

Personas:

- `Developer`;
- `Support Manager`.

### `data/raw/tech_knowledge/csv_import_rfc.md`

Содержит:

- mapping колонок;
- validation rules;
- duplicate detection;
- partial import;
- rollback strategy;
- ошибки для пользователя.

Features:

- `csv_import`;
- `tasks`;
- `permissions`.

Personas:

- `Developer`;
- `PM`;
- `Support Manager`.

### `data/raw/tech_knowledge/permissions_adr.md`

Содержит:

- роли `admin`, `manager`, `developer`, `viewer`;
- project-level permissions;
- доступ к отчетам;
- audit log;
- причины выбранной модели доступа.

Features:

- `permissions`;
- `reports`;
- `projects`.

Personas:

- `Developer`;
- `PO`;
- `PM`.

### `data/raw/user_feedback/support_tickets.csv`

CSV с 30-100 строками.

Колонки:

```text
ticket_id,created_at,customer_segment,customer_role,channel,priority,status,feature,sentiment,subject,body,satisfaction_score,resolution_time_hours
```

Пример строки:

```csv
TCK-0001,2026-03-12,enterprise,Project Manager,chat,high,resolved,notifications,negative,"Slack уведомления приходят слишком поздно","После обновления задачи уведомление в Slack приходит через 15-20 минут, команда пропускает срочные изменения.",2,31
```

### `data/raw/user_feedback/user_reviews.csv`

CSV с 20-40 отзывами.

Колонки:

```text
review_id,created_at,customer_segment,reviewer_role,rating,feature,pros,cons,request
```

Пример:

```csv
REV-0001,2026-03-20,mid_market,Product Owner,3, reports,"Удобно смотреть project health","Не хватает объяснения, почему NPS просел по конкретной функции","Хочу видеть связь отчетов с support tickets"
```

### `data/raw/business_metrics/monthly_metrics_2026_01.csv`

Сырые метрики за месяц.

Колонки:

```text
period,feature,metric_type,value,previous_value,unit,segment,related_ticket_count
```

Пример:

```csv
2026-03,notifications,adoption,48,61,percent,enterprise,47
2026-03,notifications,nps,32,41,score,enterprise,47
2026-03,csv_import,failed_imports,96,34,count,mid_market,29
```

Ingestion не должен просто векторизовать эту строку. Он должен построить digest:

```text
В марте 2026 adoption функции notifications в enterprise-сегменте снизился с 61% до 48%. Одновременно количество связанных support tickets выросло до 47.
```

### `data/raw/release_notes/release_2026_03.md`

Содержит:

- новые возможности;
- исправления;
- known issues;
- migration notes;
- влияние на фичи.

Features:

- `notifications`;
- `csv_import`;
- `reports`.

### `data/raw/release_notes/incident_notifications_delay_2026_03.md`

Содержит:

- описание инцидента;
- affected customers;
- root cause;
- workaround;
- follow-up actions.

Features:

- `notifications`;
- `integrations`;
- `webhooks`.

## Test Questions

Файл: `data/seed/persona_test_questions.jsonl`.

Формат строки:

```json
{"id":"q_po_001","persona":"PO","complexity":"high","features":["notifications"],"question":"Какие проблемы с уведомлениями сильнее всего влияют на удержание enterprise-клиентов?","expected_collections":["user_feedback","business_metrics","tech_knowledge"]}
```

Минимум:

- 5 вопросов для `PO`;
- 5 вопросов для `PM`;
- 5 вопросов для `Developer`;
- 5 вопросов для `Support Manager`.

## Persona Test Matrix

### PO

Фокус:

- бизнес-влияние;
- NPS;
- adoption;
- churn risk;
- приоритизация.

Примеры:

- "Какие фичи сильнее всего ухудшают NPS в enterprise-сегменте?"
- "Стоит ли приоритизировать исправление CSV import перед отчетами?"
- "Какие проблемы с notifications связаны с падением adoption?"
- "Какая фича выглядит самым большим churn risk?"
- "Какие технические ограничения мешают росту использования reports?"

### PM

Фокус:

- сроки;
- риски;
- зависимости;
- release planning;
- blockers.

Примеры:

- "Какие риски есть у релиза CSV import v2?"
- "Какие фичи требуют координации между backend и integrations team?"
- "Какие known issues стоит вынести из релиза?"
- "Где больше всего блокеров по sprint planning?"
- "Какие проблемы могут сорвать enterprise rollout?"

### Developer

Фокус:

- API;
- endpoint;
- payload;
- errors;
- runbook.

Примеры:

- "Какой endpoint отвечает за повторную отправку webhook?"
- "Какие ошибки возвращает CSV import при неправильном mapping?"
- "Какие роли имеют доступ к SLA report?"
- "Как устроен retry policy для Slack notifications?"
- "Какие поля обязательны при создании задачи через API?"

### Support Manager

Фокус:

- частые жалобы;
- SLA;
- escalation;
- macro replies;
- help center.

Примеры:

- "Какие жалобы по notifications повторяются чаще всего?"
- "Какой macro-ответ можно подготовить для ошибок CSV import?"
- "Какие тикеты чаще всего эскалируются?"
- "Какие проблемы стоит вынести в help center?"
- "Какие фичи ухудшают satisfaction score?"

## Внешние Датасеты

Внешние support datasets можно использовать как источник формы, но не как готовый домен.

Подход:

1. Скачать небольшой public support tickets CSV.
2. Взять структуру колонок и типовые категории.
3. Нормализовать тексты и категории под `TaskFlow AI`.
4. Оставить только безопасные synthetic/anonymized данные.

Не рекомендуется начинать с Amazon Reviews:

- они e-commerce oriented;
- плохо связываются с B2B SaaS project management;
- придется тратить время на адаптацию вместо RAG-логики.

## Definition Of Done Для Seed Dataset

Seed dataset готов, если:

- есть минимум 40-70 документов/строк;
- каждая ключевая feature покрыта минимум двумя слоями данных;
- есть минимум 20 persona-specific тестовых вопросов;
- metrics digest можно связать с support tickets;
- technical docs объясняют хотя бы часть жалоб;
- ingestion может построить Qdrant payload по схеме из `docs/database/qdrant_payload_schema.md`;
- Postgres может сохранить документы и chunks по схеме из `docs/database/postgres_schema.md`.
