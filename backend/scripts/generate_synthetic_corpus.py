import csv
from dataclasses import dataclass
from pathlib import Path


FEATURES = [
    "notifications",
    "csv_import",
    "permissions",
    "reports",
    "search",
    "webhooks",
    "integrations",
    "tasks",
    "projects",
    "sprints",
]


@dataclass(frozen=True)
class FeatureScenario:
    feature: str
    ru_name: str
    primary_problem: str
    technical_cause: str
    customer_impact: str
    metric_name: str
    related_feature: str


SCENARIOS = [
    FeatureScenario(
        feature="notifications",
        ru_name="уведомления",
        primary_problem="Slack notifications задерживаются на 15-20 минут в enterprise workspace",
        technical_cause="rate limits Slack API и слишком агрессивные retry у delivery worker",
        customer_impact="команды пропускают срочные изменения и начинают вручную проверять задачи",
        metric_name="notification_delivery_delay",
        related_feature="webhooks",
    ),
    FeatureScenario(
        feature="csv_import",
        ru_name="импорт CSV",
        primary_problem="CSV import отклоняет строки из-за неверного mapping assignee_email",
        technical_cause="валидация пользователей workspace выполняется до нормализации колонок",
        customer_impact="Project Managers не могут быстро перенести backlog из старых инструментов",
        metric_name="failed_imports",
        related_feature="tasks",
    ),
    FeatureScenario(
        feature="permissions",
        ru_name="права доступа",
        primary_problem="менеджеры не видят SLA reports после изменения project-level permissions",
        technical_cause="роль viewer не наследует доступ к отчетам проекта после миграции ролей",
        customer_impact="enterprise-команды теряют прозрачность по SLA и эскалируют тикеты",
        metric_name="access_denied_errors",
        related_feature="reports",
    ),
    FeatureScenario(
        feature="reports",
        ru_name="отчеты",
        primary_problem="SLA report показывает неполные данные после массовых изменений задач",
        technical_cause="report aggregation job читает данные до завершения task status sync",
        customer_impact="Product Owners не доверяют отчетам и экспортируют данные вручную",
        metric_name="report_accuracy_complaints",
        related_feature="tasks",
    ),
    FeatureScenario(
        feature="search",
        ru_name="поиск",
        primary_problem="поиск по assignee возвращает неполный список задач после импорта",
        technical_cause="search index lag появляется после bulk updates и CSV import jobs",
        customer_impact="PM тратят время на ручную фильтрацию задач и теряют скорость планирования",
        metric_name="search_zero_result_rate",
        related_feature="csv_import",
    ),
    FeatureScenario(
        feature="webhooks",
        ru_name="webhooks",
        primary_problem="webhook retry не доставляет события после ошибки 429",
        technical_cause="retry policy не учитывает per-workspace rate limits внешней системы",
        customer_impact="интеграции клиентов получают события с задержкой или не получают их вовсе",
        metric_name="webhook_failed_deliveries",
        related_feature="integrations",
    ),
    FeatureScenario(
        feature="integrations",
        ru_name="интеграции",
        primary_problem="Slack integration периодически теряет связь после обновления OAuth scopes",
        technical_cause="старые workspace tokens не проходят новую проверку bot permissions",
        customer_impact="команды не получают уведомления и создают дублирующие Slack threads",
        metric_name="integration_reconnect_rate",
        related_feature="notifications",
    ),
    FeatureScenario(
        feature="tasks",
        ru_name="задачи",
        primary_problem="bulk update задач иногда сбрасывает priority у части записей",
        technical_cause="partial update handler перезаписывает default priority при пустом payload field",
        customer_impact="тимлиды не видят критичные задачи в sprint board",
        metric_name="task_priority_corrections",
        related_feature="sprints",
    ),
    FeatureScenario(
        feature="projects",
        ru_name="проекты",
        primary_problem="project dashboard показывает stale health status после смены owners",
        technical_cause="project health cache не инвалидируется при изменении owner permissions",
        customer_impact="руководители принимают решения по устаревшему статусу проекта",
        metric_name="project_health_stale_views",
        related_feature="permissions",
    ),
    FeatureScenario(
        feature="sprints",
        ru_name="спринты",
        primary_problem="capacity planning не учитывает задачи, перенесенные между спринтами",
        technical_cause="sprint transfer event не обновляет capacity snapshot",
        customer_impact="PM неверно оценивают загрузку команды и риски delivery",
        metric_name="capacity_mismatch_rate",
        related_feature="tasks",
    ),
]


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    raw_root = project_root / "data" / "raw"

    _write_technical_docs(raw_root / "tech_knowledge" / "generated")
    _write_release_notes(raw_root / "release_notes" / "generated")
    _write_support_tickets(raw_root / "user_feedback" / "generated_support_tickets.csv")
    _write_user_reviews(raw_root / "user_feedback" / "generated_user_reviews.csv")
    _write_metrics(raw_root / "business_metrics" / "generated_monthly_metrics.csv")

    print("Synthetic corpus generated.")
    print("Technical markdown docs: 40")
    print("Release/incident notes: 12")
    print("Support ticket rows: 50")
    print("User review rows: 20")
    print("Metric rows: 30")
    print("Total generated documents/rows: 152")


def _write_technical_docs(target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    doc_kinds = ["architecture", "runbook", "rfc", "known_issue"]
    for scenario in SCENARIOS:
        for kind in doc_kinds:
            path = target_dir / f"{scenario.feature}_{kind}.md"
            path.write_text(_technical_doc(scenario, kind), encoding="utf-8")


def _technical_doc(scenario: FeatureScenario, kind: str) -> str:
    title = f"{scenario.ru_name.title()}: {kind.replace('_', ' ').title()}"
    return f"""# {title}

Feature: `{scenario.feature}`
Related feature: `{scenario.related_feature}`
Persona relevance: `Developer`, `PM`, `Support Manager`

## Summary

Документ описывает feature `{scenario.feature}` в TaskFlow AI. Основной сценарий связан с тем, что {scenario.primary_problem}.

## Technical Context

Техническая причина: {scenario.technical_cause}.

Связанная feature `{scenario.related_feature}` может встречаться в логах, тикетах или метриках, но основной фокус этого документа — `{scenario.feature}`.

## Customer Impact

{scenario.customer_impact}.

## Diagnostics

- проверить последние deployment events;
- сравнить affected segment: startup, mid_market, enterprise;
- посмотреть метрику `{scenario.metric_name}`;
- проверить, есть ли рост support tickets по feature `{scenario.feature}`.

## Recommended Action

Для Product Owner важно отделять прямой impact feature `{scenario.feature}` от похожих, но нерелевантных проблем в `{scenario.related_feature}`.
"""


def _write_release_notes(target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for index, scenario in enumerate(SCENARIOS[:6], start=1):
        path = target_dir / f"generated_release_2026_0{index}_{scenario.feature}.md"
        path.write_text(_release_note(scenario, month=index), encoding="utf-8")
    for index, scenario in enumerate(SCENARIOS[4:], start=1):
        path = target_dir / f"generated_incident_2026_0{index}_{scenario.feature}.md"
        path.write_text(_incident_note(scenario, month=index), encoding="utf-8")


def _release_note(scenario: FeatureScenario, month: int) -> str:
    return f"""# Release Note 2026-0{month}: {scenario.feature}

Feature: `{scenario.feature}`, `{scenario.related_feature}`

## Changes

- улучшена диагностика для `{scenario.feature}`;
- добавлены новые audit fields в support logs;
- подготовлены dashboards для метрики `{scenario.metric_name}`.

## Known Issue

Некоторые enterprise-клиенты всё ещё сообщают, что {scenario.primary_problem}.

## Product Note

Проблема похожа на `{scenario.related_feature}` по симптомам, но должна анализироваться как `{scenario.feature}`.
"""


def _incident_note(scenario: FeatureScenario, month: int) -> str:
    return f"""# Incident 2026-0{month}: {scenario.feature}

Feature: `{scenario.feature}`
Related feature: `{scenario.related_feature}`

## Summary

В enterprise-сегменте обнаружена проблема: {scenario.primary_problem}.

## Root Cause

{scenario.technical_cause}.

## Customer Impact

{scenario.customer_impact}.

## Follow-Up

- добавить alerting по `{scenario.metric_name}`;
- обновить runbook для support escalation;
- проверить, не маскируется ли проблема под `{scenario.related_feature}`.
"""


def _write_support_tickets(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index in range(50):
        scenario = SCENARIOS[index % len(SCENARIOS)]
        priority = ["low", "medium", "high", "critical"][index % 4]
        segment = ["startup", "mid_market", "enterprise", "enterprise"][index % 4]
        rows.append(
            {
                "ticket_id": f"GEN-TCK-{index + 1:04d}",
                "created_at": f"2026-04-{(index % 28) + 1:02d}",
                "customer_segment": segment,
                "customer_role": ["Product Owner", "Project Manager", "Developer", "Support Manager"][index % 4],
                "channel": ["chat", "email", "portal"][index % 3],
                "priority": priority,
                "status": ["open", "resolved", "escalated"][index % 3],
                "feature": scenario.feature,
                "sentiment": "negative" if priority in {"high", "critical"} else "neutral",
                "subject": f"{scenario.ru_name}: {scenario.primary_problem}",
                "body": (
                    f"Клиент сообщает, что {scenario.primary_problem}. "
                    f"Impact: {scenario.customer_impact}. "
                    f"Похоже на {scenario.related_feature}, но support должен классифицировать как {scenario.feature}."
                ),
                "satisfaction_score": str(2 + (index % 4)),
                "resolution_time_hours": str(8 + index * 2),
            }
        )
    _write_csv(path, rows)


def _write_user_reviews(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index in range(20):
        scenario = SCENARIOS[index % len(SCENARIOS)]
        rows.append(
            {
                "review_id": f"GEN-REV-{index + 1:04d}",
                "created_at": f"2026-04-{(index % 28) + 1:02d}",
                "customer_segment": ["mid_market", "enterprise"][index % 2],
                "reviewer_role": ["Product Owner", "Project Manager", "Developer", "Support Manager"][index % 4],
                "rating": str(2 + (index % 3)),
                "feature": scenario.feature,
                "pros": f"Feature {scenario.feature} полезна, когда работает стабильно.",
                "cons": f"Проблема: {scenario.primary_problem}.",
                "request": f"Нужны прозрачные статусы, метрика {scenario.metric_name} и понятный workaround.",
            }
        )
    _write_csv(path, rows)


def _write_metrics(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, scenario in enumerate(SCENARIOS):
        rows.extend(
            [
                _metric_row("2026-04", scenario, "adoption", 52 - index, 60 - index, "percent", 25 + index),
                _metric_row("2026-04", scenario, "support_tickets", 22 + index * 3, 12 + index, "count", 22 + index * 3),
                _metric_row("2026-04", scenario, scenario.metric_name, 30 + index * 2, 18 + index, "count", 15 + index),
            ]
        )
    _write_csv(path, rows)


def _metric_row(
    period: str,
    scenario: FeatureScenario,
    metric_type: str,
    value: int,
    previous_value: int,
    unit: str,
    related_ticket_count: int,
) -> dict[str, str]:
    return {
        "period": period,
        "feature": scenario.feature,
        "metric_type": metric_type,
        "value": str(value),
        "previous_value": str(previous_value),
        "unit": unit,
        "segment": "enterprise",
        "related_ticket_count": str(related_ticket_count),
    }


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
