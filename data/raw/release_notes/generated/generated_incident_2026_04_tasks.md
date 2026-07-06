# Incident 2026-04: tasks

Feature: `tasks`
Related feature: `sprints`

## Summary

В enterprise-сегменте обнаружена проблема: bulk update задач иногда сбрасывает priority у части записей.

## Root Cause

partial update handler перезаписывает default priority при пустом payload field.

## Customer Impact

тимлиды не видят критичные задачи в sprint board.

## Follow-Up

- добавить alerting по `task_priority_corrections`;
- обновить runbook для support escalation;
- проверить, не маскируется ли проблема под `sprints`.
