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

- support tickets могут быть важными, но не должны полностью забивать prompt;
- `max_sources_per_title=1` убирает дубли;
- при необходимости проверить `max_sources_per_source_type=2`;
- ответ не должен строиться на одном repeated generated support ticket.

## Test 5: Technical Root Cause

Запрос:

```text
Какая техническая причина задержек Slack notifications?
```

Ожидания:

- sources должны включать технические документы или incident/runbook;
- ответ должен упомянуть Slack rate limits и retry/backoff behavior, если это есть в context;
- ответ не должен превращаться только в PO summary.

## Test 6: Release Notes Focus

Запрос:

```text
Какие изменения по notifications были в release notes?
```

Ожидания:

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

## Open TODOs

- Улучшить отображение sanitized titles: сейчас prompt title может заменяться на `Источник без числовых метрик`; лучше скрывать title из prompt metadata или хранить отдельное `prompt_title`.
- Позже превратить этот checklist в автоматический evaluation script.
