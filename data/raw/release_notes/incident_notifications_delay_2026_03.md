# Incident Note: Задержки Slack Notifications В Марте 2026

Feature: `notifications`, `integrations`, `webhooks`

Persona relevance: `PO`, `PM`, `Support Manager`, `Developer`

## Summary

В период с 2026-03-10 по 2026-03-18 часть enterprise-клиентов столкнулась с задержкой Slack notifications на 15-20 минут.

## Customer Impact

- команды пропускали срочные изменения статусов задач;
- Project Managers жаловались на потерю оперативности;
- support tickets по `notifications` выросли до 47 за месяц;
- adoption notifications в enterprise-сегменте снизился с 61% до 48%.

## Root Cause

Основная причина - Slack rate limits на workspace с большим количеством событий. Delivery worker повторял отправку слишком агрессивно, что увеличивало очередь вместо стабилизации доставки.

## Mitigation

- увеличен backoff для ошибок `429`;
- enterprise tickets с priority `high` эскалируются в integrations team;
- support-команде рекомендовано предлагать временный workaround через email notifications.

## Follow-Up Actions

- обновить retry policy;
- добавить UI-индикатор delayed delivery;
- подготовить help center article;
- добавить метрику notification delivery delay в monthly report.
