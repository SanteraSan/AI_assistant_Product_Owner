# Архитектура Уведомлений TaskFlow AI

Feature: `notifications`, `integrations`, `webhooks`

Persona relevance: `Developer`, `Support Manager`

## Назначение

Notification service отвечает за доставку событий TaskFlow AI во внешние каналы: Slack, Telegram и email.

События создаются при:

- создании задачи;
- изменении статуса задачи;
- назначении исполнителя;
- приближении due date;
- нарушении SLA;
- новом комментарии.

## Поток Доставки

1. Core API публикует событие в internal event bus.
2. Notification service получает событие и определяет каналы доставки.
3. Для Slack и Telegram создается delivery job.
4. Delivery worker отправляет сообщение во внешний API.
5. Результат доставки сохраняется в delivery log.

## Retry Policy

Если внешний API возвращает временную ошибку, delivery worker делает повторные попытки.

Правила:

- максимум 5 попыток;
- первая повторная попытка через 1 минуту;
- далее используется exponential backoff;
- ошибки `429` считаются rate limit и требуют увеличенного backoff;
- ошибки `401` и `403` не повторяются автоматически.

## Known Issue

В версии `2026.03` Slack notifications могут задерживаться на 15-20 минут, если workspace превысил rate limit. Это влияет на enterprise-клиентов с большим количеством задач и комментариев.

## Support Workaround

Пока проблема не исправлена:

- предложить включить email notifications для критичных проектов;
- проверить, не отключены ли Slack notifications на уровне project settings;
- эскалировать тикеты enterprise-клиентов с priority `high`.
