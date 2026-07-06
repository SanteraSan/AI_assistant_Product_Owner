# Release Note 2026-06: webhooks

Feature: `webhooks`, `integrations`

## Changes

- улучшена диагностика для `webhooks`;
- добавлены новые audit fields в support logs;
- подготовлены dashboards для метрики `webhook_failed_deliveries`.

## Known Issue

Некоторые enterprise-клиенты всё ещё сообщают, что webhook retry не доставляет события после ошибки 429.

## Product Note

Проблема похожа на `integrations` по симптомам, но должна анализироваться как `webhooks`.
