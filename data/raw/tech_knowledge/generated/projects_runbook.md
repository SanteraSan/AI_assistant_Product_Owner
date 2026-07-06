# Проекты: Runbook

Feature: `projects`
Related feature: `permissions`
Persona relevance: `Developer`, `PM`, `Support Manager`

## Summary

Документ описывает feature `projects` в TaskFlow AI. Основной сценарий связан с тем, что project dashboard показывает stale health status после смены owners.

## Technical Context

Техническая причина: project health cache не инвалидируется при изменении owner permissions.

Связанная feature `permissions` может встречаться в логах, тикетах или метриках, но основной фокус этого документа — `projects`.

## Customer Impact

руководители принимают решения по устаревшему статусу проекта.

## Diagnostics

- проверить последние deployment events;
- сравнить affected segment: startup, mid_market, enterprise;
- посмотреть метрику `project_health_stale_views`;
- проверить, есть ли рост support tickets по feature `projects`.

## Recommended Action

Для Product Owner важно отделять прямой impact feature `projects` от похожих, но нерелевантных проблем в `permissions`.
