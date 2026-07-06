# Release Note 2026-03: permissions

Feature: `permissions`, `reports`

## Changes

- улучшена диагностика для `permissions`;
- добавлены новые audit fields в support logs;
- подготовлены dashboards для метрики `access_denied_errors`.

## Known Issue

Некоторые enterprise-клиенты всё ещё сообщают, что менеджеры не видят SLA reports после изменения project-level permissions.

## Product Note

Проблема похожа на `reports` по симптомам, но должна анализироваться как `permissions`.
