# Спринты: Architecture

Feature: `sprints`
Related feature: `tasks`
Persona relevance: `Developer`, `PM`, `Support Manager`

## Summary

Документ описывает feature `sprints` в TaskFlow AI. Основной сценарий связан с тем, что capacity planning не учитывает задачи, перенесенные между спринтами.

## Technical Context

Техническая причина: sprint transfer event не обновляет capacity snapshot.

Связанная feature `tasks` может встречаться в логах, тикетах или метриках, но основной фокус этого документа — `sprints`.

## Customer Impact

PM неверно оценивают загрузку команды и риски delivery.

## Diagnostics

- проверить последние deployment events;
- сравнить affected segment: startup, mid_market, enterprise;
- посмотреть метрику `capacity_mismatch_rate`;
- проверить, есть ли рост support tickets по feature `sprints`.

## Recommended Action

Для Product Owner важно отделять прямой impact feature `sprints` от похожих, но нерелевантных проблем в `tasks`.
