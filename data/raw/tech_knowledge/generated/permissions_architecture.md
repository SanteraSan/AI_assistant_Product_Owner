# Права Доступа: Architecture

Feature: `permissions`
Related feature: `reports`
Persona relevance: `Developer`, `PM`, `Support Manager`

## Summary

Документ описывает feature `permissions` в TaskFlow AI. Основной сценарий связан с тем, что менеджеры не видят SLA reports после изменения project-level permissions.

## Technical Context

Техническая причина: роль viewer не наследует доступ к отчетам проекта после миграции ролей.

Связанная feature `reports` может встречаться в логах, тикетах или метриках, но основной фокус этого документа — `permissions`.

## Customer Impact

enterprise-команды теряют прозрачность по SLA и эскалируют тикеты.

## Diagnostics

- проверить последние deployment events;
- сравнить affected segment: startup, mid_market, enterprise;
- посмотреть метрику `access_denied_errors`;
- проверить, есть ли рост support tickets по feature `permissions`.

## Recommended Action

Для Product Owner важно отделять прямой impact feature `permissions` от похожих, но нерелевантных проблем в `reports`.
