# Задачи: Runbook

Feature: `tasks`
Related feature: `sprints`
Persona relevance: `Developer`, `PM`, `Support Manager`

## Summary

Документ описывает feature `tasks` в TaskFlow AI. Основной сценарий связан с тем, что bulk update задач иногда сбрасывает priority у части записей.

## Technical Context

Техническая причина: partial update handler перезаписывает default priority при пустом payload field.

Связанная feature `sprints` может встречаться в логах, тикетах или метриках, но основной фокус этого документа — `tasks`.

## Customer Impact

тимлиды не видят критичные задачи в sprint board.

## Diagnostics

- проверить последние deployment events;
- сравнить affected segment: startup, mid_market, enterprise;
- посмотреть метрику `task_priority_corrections`;
- проверить, есть ли рост support tickets по feature `tasks`.

## Recommended Action

Для Product Owner важно отделять прямой impact feature `tasks` от похожих, но нерелевантных проблем в `sprints`.
