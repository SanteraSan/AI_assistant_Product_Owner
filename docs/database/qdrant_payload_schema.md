# Qdrant Payload Schema

Документ описывает payload-поля для Qdrant коллекций проекта `TaskFlow AI`.

Главное правило: вектор хранит смысл chunk, payload хранит признаки, по которым мы фильтруем, объясняем источники и связываем документы с продуктовым контекстом.

## Общие Принципы

Все Qdrant points должны иметь общий минимальный набор payload-полей:

| Поле | Тип | Обязательное | Назначение |
| --- | --- | --- | --- |
| `document_id` | string | да | ID исходного документа в PostgreSQL. |
| `chunk_id` | string | да | ID chunk в PostgreSQL. |
| `source_type` | string | да | Тип источника: `openapi`, `markdown`, `support_ticket`, `review`, `metric_digest`, `release_note`, `incident_note`, `rfc`, `adr`. |
| `source_path` | string | да | Путь к raw-файлу или логический источник. |
| `title` | string | да | Человекочитаемый заголовок документа/chunk. |
| `content` | string | да | Текст chunk, который использовался для embedding. |
| `feature` | keyword array | да | Список фич из taxonomy: `notifications`, `csv_import`, `permissions` и т.д. |
| `language` | string | да | `ru`, `en` или `mixed`. |
| `created_at` | datetime/string | нет | Дата создания исходного документа, если известна. |
| `ingested_at` | datetime/string | да | Дата загрузки в индекс. |
| `persona_relevance` | keyword array | нет | Роли, для которых chunk особенно полезен: `PO`, `PM`, `Developer`, `Support Manager`. |
| `tags` | keyword array | нет | Дополнительные признаки для фильтров и анализа. |

## MVP Коллекция: `documents`

На этапе M1 используем одну коллекцию `documents`.

Цель:

- быстро проверить end-to-end RAG;
- не тратить время на сложный collection routing;
- сохранить compatibility с будущим переносом в три коллекции.

Payload:

| Поле | Тип | Обязательное | Пример |
| --- | --- | --- | --- |
| `domain` | string | да | `tech_knowledge`, `user_feedback`, `business_metrics` |
| `source_type` | string | да | `markdown` |
| `feature` | keyword array | да | `["notifications", "integrations"]` |
| `persona_relevance` | keyword array | нет | `["PO", "Support Manager"]` |
| `period` | string | нет | `2026-03` |
| `sentiment` | string | нет | `negative` |
| `priority` | string | нет | `high` |

Пример payload:

```json
{
  "document_id": "doc_tech_notifications_arch",
  "chunk_id": "chunk_tech_notifications_arch_001",
  "domain": "tech_knowledge",
  "source_type": "markdown",
  "source_path": "data/raw/tech_knowledge/notifications_architecture.md",
  "title": "Архитектура уведомлений TaskFlow AI",
  "content": "Notification service отвечает за доставку событий в Slack, Telegram и email...",
  "feature": ["notifications", "integrations", "webhooks"],
  "language": "ru",
  "persona_relevance": ["Developer", "Support Manager"],
  "tags": ["architecture", "delivery", "retry_policy"],
  "ingested_at": "2026-07-05T00:00:00Z"
}
```

## Целевая Коллекция: `tech_knowledge`

Коллекция для технической документации, OpenAPI, ADR, RFC и архитектурных заметок.

Обязательные поля:

| Поле | Тип | Пример |
| --- | --- | --- |
| `service_name` | string | `notification-service` |
| `doc_kind` | string | `openapi`, `architecture`, `adr`, `rfc`, `runbook` |
| `feature` | keyword array | `["notifications", "webhooks"]` |
| `component` | string | `webhook-dispatcher` |
| `version` | string | `v1` |

OpenAPI-specific поля:

| Поле | Тип | Пример |
| --- | --- | --- |
| `method` | string | `POST` |
| `path` | string | `/api/v1/webhooks/retry` |
| `operation_id` | string | `retryWebhookDelivery` |
| `tag` | string | `Webhooks` |
| `status_codes` | keyword array | `["200", "400", "404", "429"]` |

Рекомендуемые фильтры:

- по `feature`, когда вопрос явно про фичу;
- по `service_name`, когда вопрос технический;
- по `method`/`path`, когда пользователь спрашивает endpoint;
- по `persona_relevance` для Developer-ответов.

## Целевая Коллекция: `user_feedback`

Коллекция для support tickets, user reviews, NPS-комментариев и жалоб.

Обязательные поля:

| Поле | Тип | Пример |
| --- | --- | --- |
| `feedback_id` | string | `ticket_00042` |
| `feedback_type` | string | `support_ticket`, `review`, `nps_comment` |
| `feature` | keyword array | `["csv_import"]` |
| `sentiment` | string | `negative`, `neutral`, `positive` |
| `priority` | string | `low`, `medium`, `high`, `critical` |
| `customer_segment` | string | `startup`, `mid_market`, `enterprise` |
| `channel` | string | `email`, `chat`, `portal`, `g2_like_review` |
| `status` | string | `open`, `resolved`, `waiting_customer`, `escalated` |

Опциональные поля:

| Поле | Тип | Пример |
| --- | --- | --- |
| `satisfaction_score` | number | `2` |
| `resolution_time_hours` | number | `31.5` |
| `customer_role` | string | `Project Manager` |
| `account_tier` | string | `enterprise` |

Рекомендуемые фильтры:

- `sentiment=negative` для поиска проблем;
- `priority in ["high", "critical"]` для escalation;
- `feature=notifications` для связывания с метриками;
- `customer_segment=enterprise` для PO/Support Manager сценариев.

## Целевая Коллекция: `business_metrics`

Коллекция для текстовых digest-документов, построенных из CSV/Excel метрик.

Сырые таблицы не векторизуем напрямую. Сначала преобразуем строки или группы строк в понятные текстовые наблюдения.

Обязательные поля:

| Поле | Тип | Пример |
| --- | --- | --- |
| `metric_digest_id` | string | `metric_2026_03_notifications_adoption` |
| `period` | string | `2026-03` |
| `metric_type` | string | `adoption`, `nps`, `retention`, `churn_risk`, `bug_count`, `resolution_time` |
| `feature` | keyword array | `["notifications"]` |
| `value` | number | `48` |
| `previous_value` | number | `61` |
| `unit` | string | `percent`, `count`, `hours`, `score` |
| `trend` | string | `up`, `down`, `flat` |

Опциональные поля:

| Поле | Тип | Пример |
| --- | --- | --- |
| `segment` | string | `enterprise` |
| `region` | string | `global` |
| `source_sheet` | string | `feature_adoption` |
| `related_ticket_count` | number | `47` |

Пример digest:

```text
В марте 2026 adoption функции notifications снизился с 61% до 48% в enterprise-сегменте. За тот же период количество support tickets по notification_delay выросло с 18 до 47, а средняя оценка удовлетворенности снизилась с 4.1 до 3.2.
```

Рекомендуемые фильтры:

- `period`, если вопрос содержит дату;
- `feature`, если вопрос связан с конкретной функцией;
- `metric_type`, если пользователь спрашивает NPS, retention, adoption или SLA;
- `segment`, если важен enterprise/mid-market контекст.

## Payload Для Personas

Поле `persona_relevance` не ограничивает доступ к документу. Оно помогает context builder лучше ранжировать или объяснять источники.

Примеры:

- `["PO"]` - бизнес-метрики, NPS, churn risk, приоритеты.
- `["PM"]` - release notes, risks, blockers, sprint/capacity.
- `["Developer"]` - OpenAPI, endpoint docs, ADR, runbooks.
- `["Support Manager"]` - support tickets, macro suggestions, SLA reports.

Если документ полезен нескольким ролям, указываем несколько значений.

## Минимальные Индексы Payload

Для Qdrant payload indexes стоит начать с полей:

- `domain`;
- `source_type`;
- `feature`;
- `persona_relevance`;
- `period`;
- `metric_type`;
- `sentiment`;
- `priority`;
- `service_name`;
- `method`;
- `path`.

Не нужно индексировать все поля сразу. Индексируем только то, что реально используем в фильтрах.

## Правила Chunking

`tech_knowledge`:

- 400-700 токенов;
- overlap 50-100;
- OpenAPI лучше резать по endpoint или tag.

`user_feedback`:

- одна строка CSV = один документ;
- длинные письма можно резать по 150-300 токенов;
- не смешивать несколько клиентов в одном chunk.

`business_metrics`:

- один digest = один документ;
- digest должен содержать период, feature, изменение метрики и возможную связь с feedback.

## Проверки Качества

Перед ingestion проверяем:

- у каждого chunk есть `feature`;
- у каждого chunk есть `source_type`;
- нет пустого `content`;
- язык указан явно;
- `feature` входит в taxonomy из `docs/product/taskflow_ai_product.md`;
- `document_id` и `chunk_id` синхронизированы с PostgreSQL;
- metric digest содержит человечески понятный текст, а не только числа.
