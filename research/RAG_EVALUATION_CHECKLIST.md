# RAG Evaluation Checklist

Этот checklist нужен для ручной проверки retrieval policy, prompt-following и поведения моделей после изменений в RAG pipeline.

## Как Прогонять

1. Перезапустить backend после изменений.
2. Прогнать один и тот же запрос на `gemma3:12b` и `qwen2.5:14b`.
3. Сохранять компактный JSON:

```bash
jq '{model,response,latency_ms,score_threshold,source_types,query_hints,context_policy,retrieval,sources:[.sources[] | {score,title,source_type,feature}]}'
```

4. Отмечать не только качество ответа, но и то, какие policy layers сработали:

- `score_threshold`;
- `source_types`;
- `query_hints`;
- `context_policy`;
- `retrieval.candidate_k`;
- `retrieval.final_top_k`;
- `diversity`.

## Автоматизированный Прогон

Backend script `scripts.run_rag_evaluation` прогоняет сценарии из этого checklist через реальный `/rag/chat` API и сохраняет результаты в PostgreSQL:

```bash
cd /home/santera/Projects/backend
source .venv/bin/activate
python -m scripts.run_rag_evaluation --models gemma3:12b --limit-scenarios 1 --top-k 3
```

Для полного сравнения можно передать несколько моделей:

```bash
python -m scripts.run_rag_evaluation \
  --models qwen2.5:7b-instruct-q8_0 qwen2.5:14b gemma3:12b \
  --top-k 5 \
  --notes "Full checklist run"
```

Важно: автоматические `quality_flags` являются быстрыми эвристиками, а не заменой ручной оценки. Они помогают найти очевидные регрессии: пустой ответ, неправильный router intent, отсутствие expected source type или нарушение простого negative constraint.

## Базовые Критерии

- `groundedness`: ответ не выдумывает факты вне context.
- `intent_fit`: retrieval strategy соответствует типу вопроса.
- `negative_instruction_following`: модель соблюдает ограничения вроде "без метрик".
- `source_diversity`: prompt не забит однотипными chunks.
- `persona_fit`: ответ полезен Product Owner.
- `model_delta`: понятна разница поведения `gemma3:12b` и `qwen2.5:14b`.

## Test 1: Metric Intent

Запрос:

```text
Какие метрики по notifications изменились у enterprise-клиентов?
```

Ожидания:

- `query_hints.metric_intent=true`;
- `query_hints.applied_hints` содержит `metric_source_types` и `metric_score_threshold`, если параметры не переданы вручную;
- `score_threshold=0.60`;
- среди sources есть `metric_row`;
- ответ использует `notification_delivery_delay` и не выдумывает другие метрики.

## Test 2: Negative Metric Intent

Запрос:

```text
Какие проблемы с notifications важны для enterprise-клиентов, без метрик?
```

Ожидания:

- `query_hints.metric_negative_marker=true`;
- `query_hints.metric_intent=false`;
- `query_hints.applied_hints=[]`;
- `score_threshold=0.68`;
- `context_policy.numeric_line_sanitization=true`;
- ответ не упоминает проценты, ticket counters, adoption и numeric KPI;
- ответ сохраняет качественный impact: пропуск срочных изменений, потеря оперативности, ручные проверки.

## Test 3: General PO Problem Summary

Запрос:

```text
Какие проблемы с notifications влияют на enterprise-клиентов?
```

Ожидания:

- `features=["notifications"]` либо auto feature extraction определяет `notifications`;
- `score_threshold=0.68`;
- top sources включают разные evidence types: `incident_note`, `support_ticket`, `release_note`;
- если включен `max_sources_per_title=1`, нет дублей с одинаковым title;
- ответ может использовать метрики, потому что пользователь их не запрещал.

## Test 4: Source Diversity Stress

Запрос:

```text
Какие жалобы клиентов чаще всего встречаются по notifications?
```

Ожидания:

- `query_hints.support_feedback_intent=true`;
- если `source_types` не переданы вручную, router применяет `support_feedback_source_types`;
- sources должны приоритизировать `support_ticket`, затем `incident_note` и `metric_row`;
- markdown/release docs не должны доминировать в context;
- support tickets могут быть важными, но не должны полностью забивать prompt;
- `max_sources_per_title=1` убирает дубли;
- при необходимости проверить `max_sources_per_source_type=2`;
- ответ не должен строиться на одном repeated generated support ticket.

## Test 5: Technical Root Cause

Запрос:

```text
Какая техническая причина задержек Slack notifications?
```

Дополнительные формулировки:

```text
Почему Slack notifications задерживаются у enterprise-клиентов?
Что происходит в delivery worker при отправке notifications?
Как retry/backoff влияет на задержки уведомлений?
Это проблема Slack API или нашего backend?
```

Ожидания:

- `query_hints.technical_root_cause_intent=true`;
- если `source_types` не переданы вручную, router применяет `technical_root_cause_source_types`;
- если `score_threshold` не передан вручную, router снижает threshold до `0.60`;
- sources должны включать технические документы или incident/runbook;
- ответ должен упомянуть Slack rate limits и retry/backoff behavior, если это есть в context;
- ответ не должен превращаться только в PO summary.

## Test 6: Release Notes Focus

Запрос:

```text
Какие изменения по notifications были в release notes?
```

Ожидания:

- `query_hints.release_notes_intent=true`;
- `query_hints.metric_intent=false`;
- если `source_types` не переданы вручную, router применяет `release_notes_source_types`;
- sources должны приоритизировать `release_note`;
- incident/support sources могут быть вспомогательными, но не должны подменять release note answer;
- ответ должен отделять shipped changes от проблем/инцидентов.

## Test 7: No-Answer Groundedness

Запрос:

```text
Сколько ARR мы потеряем из-за проблем с notifications?
```

Ожидания:

- модель должна сказать, что в context нет данных для точного ARR loss;
- не должна выдумывать revenue loss, churn probability или список клиентов;
- должна перечислить недостающие данные: ARR по клиентам, renewal dates, account health.

## Test 8: Incident Summary

Запрос:

```text
Что случилось с notifications в мартовском инциденте и какой был impact?
```

Ожидания:

- `query_hints.incident_intent=true`;
- если `source_types` не переданы вручную, router применяет `incident_source_types`;
- sources должны приоритизировать `incident_note`, затем `support_ticket` и `metric_row`;
- ответ должен описать что случилось, impact, mitigation/follow-up;
- ответ не должен превращаться только в technical root-cause или release notes summary.

## Test 9: Follow-Up Continuation

Запросы в одной `session_id`:

```text
Q1: Какие проблемы с notifications влияют на enterprise-клиентов?
Q2: А какие из этих проблем самые критичные?
```

Ожидания:

- `conversation_context.used=true`;
- `conversation_context.mode="follow_up_rewrite"`;
- `conversation_context.follow_up_detected=true`;
- `conversation_context.carried_features` содержит `notifications`;
- `retrieval.final_top_k > 0`;
- sources остаются связаны с `notifications`.

## Test 10: Topic Switch

Запросы в одной `session_id`:

```text
Q1: Какие проблемы с notifications влияют на enterprise-клиентов?
Q2: А что с csv_import?
```

Ожидания:

- backend не переносит старую тему `notifications` в retrieval query;
- `conversation_context.used=false`;
- `conversation_context.mode="topic_switch_or_standalone"`;
- `conversation_context.current_features` содержит `csv_import`;
- sources переключаются на `csv_import`.

## Open TODOs

- Улучшить отображение sanitized titles: сейчас prompt title может заменяться на `Источник без числовых метрик`; лучше скрывать title из prompt metadata или хранить отдельное `prompt_title`.
- Позже превратить этот checklist в автоматический evaluation script.
