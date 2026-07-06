# Incident 2026-05: projects

Feature: `projects`
Related feature: `permissions`

## Summary

В enterprise-сегменте обнаружена проблема: project dashboard показывает stale health status после смены owners.

## Root Cause

project health cache не инвалидируется при изменении owner permissions.

## Customer Impact

руководители принимают решения по устаревшему статусу проекта.

## Follow-Up

- добавить alerting по `project_health_stale_views`;
- обновить runbook для support escalation;
- проверить, не маскируется ли проблема под `permissions`.
