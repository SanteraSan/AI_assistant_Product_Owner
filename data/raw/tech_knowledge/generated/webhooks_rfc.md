# Webhooks: Rfc

Feature: `webhooks`
Related feature: `integrations`
Persona relevance: `Developer`, `PM`, `Support Manager`

## Summary

Документ описывает feature `webhooks` в TaskFlow AI. Основной сценарий связан с тем, что webhook retry не доставляет события после ошибки 429.

## Technical Context

Техническая причина: retry policy не учитывает per-workspace rate limits внешней системы.

Связанная feature `integrations` может встречаться в логах, тикетах или метриках, но основной фокус этого документа — `webhooks`.

## Customer Impact

интеграции клиентов получают события с задержкой или не получают их вовсе.

## Diagnostics

- проверить последние deployment events;
- сравнить affected segment: startup, mid_market, enterprise;
- посмотреть метрику `webhook_failed_deliveries`;
- проверить, есть ли рост support tickets по feature `webhooks`.

## Recommended Action

Для Product Owner важно отделять прямой impact feature `webhooks` от похожих, но нерелевантных проблем в `integrations`.
