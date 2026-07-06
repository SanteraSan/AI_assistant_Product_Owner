# Incident 2026-01: search

Feature: `search`
Related feature: `csv_import`

## Summary

В enterprise-сегменте обнаружена проблема: поиск по assignee возвращает неполный список задач после импорта.

## Root Cause

search index lag появляется после bulk updates и CSV import jobs.

## Customer Impact

PM тратят время на ручную фильтрацию задач и теряют скорость планирования.

## Follow-Up

- добавить alerting по `search_zero_result_rate`;
- обновить runbook для support escalation;
- проверить, не маскируется ли проблема под `csv_import`.
