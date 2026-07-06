# Incident 2026-06: sprints

Feature: `sprints`
Related feature: `tasks`

## Summary

В enterprise-сегменте обнаружена проблема: capacity planning не учитывает задачи, перенесенные между спринтами.

## Root Cause

sprint transfer event не обновляет capacity snapshot.

## Customer Impact

PM неверно оценивают загрузку команды и риски delivery.

## Follow-Up

- добавить alerting по `capacity_mismatch_rate`;
- обновить runbook для support escalation;
- проверить, не маскируется ли проблема под `tasks`.
