# Release Note 2026-01: notifications

Feature: `notifications`, `webhooks`

## Changes

- улучшена диагностика для `notifications`;
- добавлены новые audit fields в support logs;
- подготовлены dashboards для метрики `notification_delivery_delay`.

## Known Issue

Некоторые enterprise-клиенты всё ещё сообщают, что Slack notifications задерживаются на 15-20 минут в enterprise workspace.

## Product Note

Проблема похожа на `webhooks` по симптомам, но должна анализироваться как `notifications`.
