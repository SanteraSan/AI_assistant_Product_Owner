# Incident 2026-03: integrations

Feature: `integrations`
Related feature: `notifications`

## Summary

В enterprise-сегменте обнаружена проблема: Slack integration периодически теряет связь после обновления OAuth scopes.

## Root Cause

старые workspace tokens не проходят новую проверку bot permissions.

## Customer Impact

команды не получают уведомления и создают дублирующие Slack threads.

## Follow-Up

- добавить alerting по `integration_reconnect_rate`;
- обновить runbook для support escalation;
- проверить, не маскируется ли проблема под `notifications`.
