# Поиск: Architecture

Feature: `search`
Related feature: `csv_import`
Persona relevance: `Developer`, `PM`, `Support Manager`

## Summary

Документ описывает feature `search` в TaskFlow AI. Основной сценарий связан с тем, что поиск по assignee возвращает неполный список задач после импорта.

## Technical Context

Техническая причина: search index lag появляется после bulk updates и CSV import jobs.

Связанная feature `csv_import` может встречаться в логах, тикетах или метриках, но основной фокус этого документа — `search`.

## Customer Impact

PM тратят время на ручную фильтрацию задач и теряют скорость планирования.

## Diagnostics

- проверить последние deployment events;
- сравнить affected segment: startup, mid_market, enterprise;
- посмотреть метрику `search_zero_result_rate`;
- проверить, есть ли рост support tickets по feature `search`.

## Recommended Action

Для Product Owner важно отделять прямой impact feature `search` от похожих, но нерелевантных проблем в `csv_import`.
