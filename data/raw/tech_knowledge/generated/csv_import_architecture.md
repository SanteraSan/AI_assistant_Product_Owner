# Импорт Csv: Architecture

Feature: `csv_import`
Related feature: `tasks`
Persona relevance: `Developer`, `PM`, `Support Manager`

## Summary

Документ описывает feature `csv_import` в TaskFlow AI. Основной сценарий связан с тем, что CSV import отклоняет строки из-за неверного mapping assignee_email.

## Technical Context

Техническая причина: валидация пользователей workspace выполняется до нормализации колонок.

Связанная feature `tasks` может встречаться в логах, тикетах или метриках, но основной фокус этого документа — `csv_import`.

## Customer Impact

Project Managers не могут быстро перенести backlog из старых инструментов.

## Diagnostics

- проверить последние deployment events;
- сравнить affected segment: startup, mid_market, enterprise;
- посмотреть метрику `failed_imports`;
- проверить, есть ли рост support tickets по feature `csv_import`.

## Recommended Action

Для Product Owner важно отделять прямой impact feature `csv_import` от похожих, но нерелевантных проблем в `tasks`.
