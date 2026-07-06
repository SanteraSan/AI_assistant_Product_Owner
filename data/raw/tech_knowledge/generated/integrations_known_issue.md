# Интеграции: Known Issue

Feature: `integrations`
Related feature: `notifications`
Persona relevance: `Developer`, `PM`, `Support Manager`

## Summary

Документ описывает feature `integrations` в TaskFlow AI. Основной сценарий связан с тем, что Slack integration периодически теряет связь после обновления OAuth scopes.

## Technical Context

Техническая причина: старые workspace tokens не проходят новую проверку bot permissions.

Связанная feature `notifications` может встречаться в логах, тикетах или метриках, но основной фокус этого документа — `integrations`.

## Customer Impact

команды не получают уведомления и создают дублирующие Slack threads.

## Diagnostics

- проверить последние deployment events;
- сравнить affected segment: startup, mid_market, enterprise;
- посмотреть метрику `integration_reconnect_rate`;
- проверить, есть ли рост support tickets по feature `integrations`.

## Recommended Action

Для Product Owner важно отделять прямой impact feature `integrations` от похожих, но нерелевантных проблем в `notifications`.
