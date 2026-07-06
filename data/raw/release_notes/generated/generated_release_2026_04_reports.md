# Release Note 2026-04: reports

Feature: `reports`, `tasks`

## Changes

- улучшена диагностика для `reports`;
- добавлены новые audit fields в support logs;
- подготовлены dashboards для метрики `report_accuracy_complaints`.

## Known Issue

Некоторые enterprise-клиенты всё ещё сообщают, что SLA report показывает неполные данные после массовых изменений задач.

## Product Note

Проблема похожа на `tasks` по симптомам, но должна анализироваться как `reports`.
