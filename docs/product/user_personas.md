# User Personas And Prompt Context

Этот документ фиксирует роли пользователей `TaskFlow AI` и то, как persona должна влиять на ответы ассистента.

На ранних этапах persona - это не авторизация и не permissions model. Это контекст ответа:

- какой фокус выбрать;
- какие источники предпочесть;
- какие детали показать;
- каким языком объяснять результат.

## Общий Формат Persona Context

```json
{
  "active_persona": "PO",
  "response_focus": ["business_impact", "prioritization", "metrics"],
  "preferred_sources": ["business_metrics", "user_feedback", "tech_knowledge"],
  "answer_style": "Кратко объяснить вывод, показать влияние на продукт, предложить следующий шаг."
}
```

## PO

Product Owner смотрит на продукт через влияние на пользователей и бизнес.

Фокус ответа:

- NPS;
- adoption;
- retention;
- churn risk;
- customer segment;
- приоритизация;
- trade-offs.

Предпочтительные источники:

- `business_metrics`;
- `user_feedback`;
- `release_notes`;
- `tech_knowledge`, если нужно объяснить причину.

Стиль ответа:

- начать с продуктового вывода;
- показать evidence из метрик и feedback;
- предложить приоритет или next step;
- технические детали давать только если они объясняют бизнес-влияние.

Пример ответа:

```text
Главный риск для PO - падение adoption notifications в enterprise-сегменте. Метрики показывают снижение с 61% до 48%, а support tickets по задержкам выросли до 47. Приоритет стоит поднять, потому что проблема влияет на ежедневный workflow команд и может ухудшать retention.
```

## PM

Project Manager смотрит на сроки, ресурсы, зависимости и риски релиза.

Фокус ответа:

- blockers;
- dependencies;
- scope;
- release risk;
- team coordination;
- rollout plan.

Предпочтительные источники:

- `release_notes`;
- `tech_knowledge`;
- `user_feedback`;
- `business_metrics` для оценки impact.

Стиль ответа:

- структурировать риски;
- отделять confirmed issues от assumptions;
- указывать зависимости;
- предлагать план действий.

Пример ответа:

```text
Для релиза CSV import v2 главный риск - validation errors и rollback behavior. Support tickets показывают рост ошибок импорта, а RFC описывает незавершенную стратегию partial rollback. Для PM это blocker перед enterprise rollout.
```

## Developer

Developer смотрит на API, ограничения, ошибки и конкретную реализацию.

Фокус ответа:

- endpoint;
- method;
- payload;
- status codes;
- retry policy;
- data model;
- technical constraints.

Предпочтительные источники:

- `tech_knowledge`;
- OpenAPI chunks;
- ADR/RFC;
- incident notes.

Стиль ответа:

- дать конкретный endpoint или компонент;
- перечислить важные поля;
- указать ошибки;
- сослаться на ограничения и runbook.

Пример ответа:

```text
За повторную отправку webhook отвечает `POST /api/v1/webhooks/retry`. Endpoint принимает `delivery_id` и возвращает `404`, если delivery не найден, и `429`, если превышен retry limit. Retry policy описана в документе notification service.
```

## Support Manager

Support Manager смотрит на повторяемость проблем, SLA и готовые действия для support-команды.

Фокус ответа:

- частые жалобы;
- escalation;
- SLA;
- customer satisfaction;
- macro reply;
- help center gaps.

Предпочтительные источники:

- `user_feedback`;
- `business_metrics`;
- `release_notes`;
- `tech_knowledge` для workaround.

Стиль ответа:

- группировать жалобы по паттернам;
- показывать частоту и severity;
- предлагать macro-ответ;
- выделять, что нужно эскалировать в product/engineering.

Пример ответа:

```text
Чаще всего пользователи жалуются на задержку Slack notifications после изменения статуса задачи. Для support можно подготовить macro с объяснением задержек, workaround через email notifications и обещанием исправления в следующем patch release.
```

## Prompt Template Fragment

Фрагмент, который можно добавлять в system/developer prompt:

```text
Текущая роль пользователя: {active_persona}.

Адаптируй ответ под роль:
- PO: бизнес-влияние, метрики, приоритеты, retention/adoption/NPS.
- PM: сроки, риски, зависимости, blockers, release planning.
- Developer: API, endpoint, payload, status codes, технические ограничения.
- Support Manager: частые жалобы, SLA, escalation, macro replies, help center.

Не выдумывай факты. Если в найденном контексте нет данных, явно скажи, чего не хватает.
```

## Evaluation Rules

Ответ считается хорошим, если:

- использует найденные источники;
- отвечает на вопрос именно с точки зрения persona;
- не перегружает роль нерелевантными деталями;
- явно отделяет evidence от предположений;
- предлагает следующий шаг, полезный для роли.

Ответ считается плохим, если:

- Developer получает только бизнес-обобщение без endpoint/details;
- PO получает низкоуровневый API-ответ без business impact;
- Support Manager не получает повторяемые паттерны и actionable macro;
- PM не получает риски, зависимости или план действий;
- ассистент выдумывает метрики или источники.
