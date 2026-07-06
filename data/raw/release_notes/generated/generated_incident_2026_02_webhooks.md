# Incident 2026-02: webhooks

Feature: `webhooks`
Related feature: `integrations`

## Summary

В enterprise-сегменте обнаружена проблема: webhook retry не доставляет события после ошибки 429.

## Root Cause

retry policy не учитывает per-workspace rate limits внешней системы.

## Customer Impact

интеграции клиентов получают события с задержкой или не получают их вовсе.

## Follow-Up

- добавить alerting по `webhook_failed_deliveries`;
- обновить runbook для support escalation;
- проверить, не маскируется ли проблема под `integrations`.
