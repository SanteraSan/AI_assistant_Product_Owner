# Отчеты: Runbook

Feature: `reports`
Related feature: `tasks`
Persona relevance: `Developer`, `PM`, `Support Manager`

## Summary

Документ описывает feature `reports` в TaskFlow AI. Основной сценарий связан с тем, что SLA report показывает неполные данные после массовых изменений задач.

## Technical Context

Техническая причина: report aggregation job читает данные до завершения task status sync.

Связанная feature `tasks` может встречаться в логах, тикетах или метриках, но основной фокус этого документа — `reports`.

## Customer Impact

Product Owners не доверяют отчетам и экспортируют данные вручную.

## Diagnostics

- проверить последние deployment events;
- сравнить affected segment: startup, mid_market, enterprise;
- посмотреть метрику `report_accuracy_complaints`;
- проверить, есть ли рост support tickets по feature `reports`.

## Recommended Action

Для Product Owner важно отделять прямой impact feature `reports` от похожих, но нерелевантных проблем в `tasks`.
