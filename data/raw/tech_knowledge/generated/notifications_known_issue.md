# Уведомления: Known Issue

Feature: `notifications`
Related feature: `webhooks`
Persona relevance: `Developer`, `PM`, `Support Manager`

## Summary

Документ описывает feature `notifications` в TaskFlow AI. Основной сценарий связан с тем, что Slack notifications задерживаются на 15-20 минут в enterprise workspace.

## Technical Context

Техническая причина: rate limits Slack API и слишком агрессивные retry у delivery worker.

Связанная feature `webhooks` может встречаться в логах, тикетах или метриках, но основной фокус этого документа — `notifications`.

## Customer Impact

команды пропускают срочные изменения и начинают вручную проверять задачи.

## Diagnostics

- проверить последние deployment events;
- сравнить affected segment: startup, mid_market, enterprise;
- посмотреть метрику `notification_delivery_delay`;
- проверить, есть ли рост support tickets по feature `notifications`.

## Recommended Action

Для Product Owner важно отделять прямой impact feature `notifications` от похожих, но нерелевантных проблем в `webhooks`.
