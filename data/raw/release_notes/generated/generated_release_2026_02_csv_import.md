# Release Note 2026-02: csv_import

Feature: `csv_import`, `tasks`

## Changes

- улучшена диагностика для `csv_import`;
- добавлены новые audit fields в support logs;
- подготовлены dashboards для метрики `failed_imports`.

## Known Issue

Некоторые enterprise-клиенты всё ещё сообщают, что CSV import отклоняет строки из-за неверного mapping assignee_email.

## Product Note

Проблема похожа на `tasks` по симптомам, но должна анализироваться как `csv_import`.
