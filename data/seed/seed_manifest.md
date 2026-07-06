# Seed Manifest

Манифест стартового набора данных `TaskFlow AI`.

## Уже Добавлено

| Файл | Тип | Основные Features | Назначение |
| --- | --- | --- | --- |
| `data/raw/tech_knowledge/taskflow_openapi.yaml` | OpenAPI | `tasks`, `csv_import`, `reports`, `webhooks`, `notifications` | Технический слой для Developer-вопросов. |
| `data/raw/tech_knowledge/notifications_architecture.md` | Markdown tech doc | `notifications`, `integrations`, `webhooks` | Объясняет задержки уведомлений и retry policy. |
| `data/raw/tech_knowledge/csv_import_rfc.md` | RFC | `csv_import`, `tasks`, `permissions` | Описывает правила CSV import и ошибки. |
| `data/raw/user_feedback/support_tickets_sample.csv` | CSV feedback | `notifications`, `csv_import`, `permissions`, `webhooks`, `search` | Минимальный пример support tickets. |
| `data/raw/business_metrics/monthly_metrics_2026_03_sample.csv` | CSV metrics | `notifications`, `csv_import`, `reports`, `permissions`, `search`, `webhooks` | Метрики, связанные с feedback. |
| `data/raw/release_notes/incident_notifications_delay_2026_03.md` | Incident note | `notifications`, `integrations`, `webhooks` | Связка между incident, support и metrics. |
| `data/seed/persona_test_questions.jsonl` | Eval questions | все основные features | 20 тестовых вопросов по personas. |

## Synthetic Corpus Для Retrieval Stress Test

Для проверки RAG на более шумном корпусе добавлен deterministic generated dataset.

Генератор:

```text
backend/scripts/generate_synthetic_corpus.py
```

Сгенерированные данные:

| Путь | Тип | Количество | Назначение |
| --- | --- | ---: | --- |
| `data/raw/tech_knowledge/generated/*.md` | Technical docs | 40 | Architecture/runbook/RFC/known issue по 10 features. |
| `data/raw/release_notes/generated/*.md` | Release/incident notes | 12 | Похожие incident/release scenarios с пересечениями features. |
| `data/raw/user_feedback/generated_support_tickets.csv` | Support tickets | 50 rows | Шумные и похожие тикеты по всем features. |
| `data/raw/user_feedback/generated_user_reviews.csv` | User reviews | 20 rows | Отзывы разных ролей по feature-проблемам. |
| `data/raw/business_metrics/generated_monthly_metrics.csv` | Metrics | 30 rows | Метрики adoption/support_tickets/feature-specific counters. |

Всего generated corpus:

```text
152 документов/строк
```

Цель:

- проверить, начнет ли retrieval шуметь при росте корпуса;
- проверить пользу `features` metadata filter;
- проверить пользу `score_threshold`;
- подготовить почву для reranking и multi-collection retrieval.

## Нужно Добавить Позже

Для полноценного M1/M6 dataset:

- `data/raw/tech_knowledge/permissions_adr.md`;
- `data/raw/tech_knowledge/reports_access_model.md`;
- `data/raw/tech_knowledge/search_indexing_runbook.md`;
- `data/raw/user_feedback/user_reviews.csv`;
- `data/raw/business_metrics/monthly_metrics_2026_01.csv`;
- `data/raw/business_metrics/monthly_metrics_2026_02.csv`;
- `data/raw/release_notes/release_2026_03.md`;
- `data/raw/release_notes/incident_csv_import_validation_2026_03.md`.

## Ingestion Order

Для первого ingestion smoke test:

1. Markdown docs из `data/raw/tech_knowledge`.
2. Incident notes из `data/raw/release_notes`.
3. CSV feedback из `data/raw/user_feedback`.
4. CSV metrics из `data/raw/business_metrics` с преобразованием в digest.
5. OpenAPI как отдельный parser после простого Markdown/CSV пути.

## Контроль Связности

Перед загрузкой в Qdrant проверить:

- `notifications` встречается в tech docs, support tickets, metrics и incident note;
- `csv_import` встречается в RFC, support tickets и metrics;
- `permissions` встречается в support tickets и metrics, но требует отдельный ADR;
- `reports` встречается в OpenAPI и metrics, но требует отдельный документ по access model;
- `search` представлен только в feedback/metrics и требует runbook;
- `webhooks` представлен в OpenAPI, tech docs, incident и metrics.

## MVP Gap

Текущий starter dataset достаточен для проектирования ingestion и первых локальных тестов, но недостаточен для финального demo. Перед demo нужно расширить user feedback минимум до 30 строк и добавить документы по `permissions`, `reports` и `search`.
