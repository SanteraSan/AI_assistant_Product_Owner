# Release Note 2026-05: search

Feature: `search`, `csv_import`

## Changes

- улучшена диагностика для `search`;
- добавлены новые audit fields в support logs;
- подготовлены dashboards для метрики `search_zero_result_rate`.

## Known Issue

Некоторые enterprise-клиенты всё ещё сообщают, что поиск по assignee возвращает неполный список задач после импорта.

## Product Note

Проблема похожа на `csv_import` по симптомам, но должна анализироваться как `search`.
