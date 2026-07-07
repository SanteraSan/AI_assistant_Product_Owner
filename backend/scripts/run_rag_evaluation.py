import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import get_settings
from app.db.session import (
    create_engine,
    create_session_factory,
    database_available,
    init_db,
)
from app.services.evaluation_service import EvaluationService


@dataclass(frozen=True)
class EvaluationScenario:
    id: str
    name: str
    prompt: str
    turns: tuple[str, ...] = ()


SCENARIOS = [
    EvaluationScenario(
        id="metric_intent",
        name="Metric Intent",
        prompt="Какие метрики по notifications изменились у enterprise-клиентов?",
    ),
    EvaluationScenario(
        id="negative_metric_intent",
        name="Negative Metric Intent",
        prompt="Какие проблемы с notifications важны для enterprise-клиентов, без метрик?",
    ),
    EvaluationScenario(
        id="general_po_summary",
        name="General PO Problem Summary",
        prompt="Какие проблемы с notifications влияют на enterprise-клиентов?",
    ),
    EvaluationScenario(
        id="source_diversity_stress",
        name="Source Diversity Stress",
        prompt="Какие жалобы клиентов чаще всего встречаются по notifications?",
    ),
    EvaluationScenario(
        id="technical_root_cause",
        name="Technical Root Cause",
        prompt="Какая техническая причина задержек Slack notifications?",
    ),
    EvaluationScenario(
        id="release_notes_focus",
        name="Release Notes Focus",
        prompt="Какие изменения по notifications были в release notes?",
    ),
    EvaluationScenario(
        id="no_answer_groundedness",
        name="No-Answer Groundedness",
        prompt="Сколько ARR мы потеряем из-за проблем с notifications?",
    ),
    EvaluationScenario(
        id="incident_summary",
        name="Incident Summary",
        prompt="Что случилось с notifications в мартовском инциденте и какой был impact?",
    ),
    EvaluationScenario(
        id="follow_up_continuation",
        name="Follow-Up Continuation",
        prompt=(
            "Q1: Какие проблемы с notifications влияют на enterprise-клиентов?\n"
            "Q2: А какие из этих проблем самые критичные?"
        ),
        turns=(
            "Какие проблемы с notifications влияют на enterprise-клиентов?",
            "А какие из этих проблем самые критичные?",
        ),
    ),
    EvaluationScenario(
        id="topic_switch",
        name="Topic Switch",
        prompt=(
            "Q1: Какие проблемы с notifications влияют на enterprise-клиентов?\n"
            "Q2: А что с csv_import?"
        ),
        turns=(
            "Какие проблемы с notifications влияют на enterprise-клиентов?",
            "А что с csv_import?",
        ),
    ),
    EvaluationScenario(
        id="follow_up_action_plan",
        name="Follow-Up Action Plan",
        prompt=(
            "Q1: Какие проблемы с notifications влияют на enterprise-клиентов?\n"
            "Q2: Что с этим делать в первую очередь?"
        ),
        turns=(
            "Какие проблемы с notifications влияют на enterprise-клиентов?",
            "Что с этим делать в первую очередь?",
        ),
    ),
    EvaluationScenario(
        id="explicit_topic_switch",
        name="Explicit Topic Switch",
        prompt=(
            "Q1: Какие проблемы с notifications влияют на enterprise-клиентов?\n"
            "Q2: Ок, забудь notifications, а теперь про permissions"
        ),
        turns=(
            "Какие проблемы с notifications влияют на enterprise-клиентов?",
            "Ок, забудь notifications, а теперь про permissions",
        ),
    ),
    EvaluationScenario(
        id="follow_up_metric_intent",
        name="Follow-Up Metric Intent",
        prompt=(
            "Q1: Какие проблемы с notifications влияют на enterprise-клиентов?\n"
            "Q2: А какие метрики по ним изменились?"
        ),
        turns=(
            "Какие проблемы с notifications влияют на enterprise-клиентов?",
            "А какие метрики по ним изменились?",
        ),
    ),
    EvaluationScenario(
        id="follow_up_negative_metric",
        name="Follow-Up Negative Metric",
        prompt=(
            "Q1: Какие проблемы с notifications влияют на enterprise-клиентов?\n"
            "Q2: А можешь без метрик?"
        ),
        turns=(
            "Какие проблемы с notifications влияют на enterprise-клиентов?",
            "А можешь без метрик?",
        ),
    ),
    EvaluationScenario(
        id="follow_up_incident",
        name="Follow-Up Incident",
        prompt=(
            "Q1: Какие проблемы с notifications влияют на enterprise-клиентов?\n"
            "Q2: А что было в мартовском инциденте?"
        ),
        turns=(
            "Какие проблемы с notifications влияют на enterprise-клиентов?",
            "А что было в мартовском инциденте?",
        ),
    ),
    EvaluationScenario(
        id="summary_long_follow_up",
        name="Summary Long Follow-Up",
        prompt=(
            "Q1: Какие проблемы с notifications влияют на enterprise-клиентов?\n"
            "Q2-Q4: уточняющие follow-up без явного feature\n"
            "Q5: А какие из них самые критичные?"
        ),
        turns=(
            "Какие проблемы с notifications влияют на enterprise-клиентов?",
            "Понял. Какие риски для команды?",
            "Как это объяснить PO?",
            "Что с этим делать в первую очередь?",
            "А какие из них самые критичные?",
        ),
    ),
    EvaluationScenario(
        id="summary_topic_switch",
        name="Summary Topic Switch",
        prompt=(
            "Q1: Какие проблемы с notifications влияют на enterprise-клиентов?\n"
            "Q2-Q4: follow-up без явного feature\n"
            "Q5: Ок, забудь notifications, а теперь про permissions"
        ),
        turns=(
            "Какие проблемы с notifications влияют на enterprise-клиентов?",
            "Понял. Какие риски для команды?",
            "Как это объяснить PO?",
            "Что с этим делать в первую очередь?",
            "Ок, забудь notifications, а теперь про permissions",
        ),
    ),
    EvaluationScenario(
        id="summary_metric_follow_up",
        name="Summary Metric Follow-Up",
        prompt=(
            "Q1: Какие проблемы с notifications влияют на enterprise-клиентов?\n"
            "Q2-Q4: follow-up без явного feature\n"
            "Q5: А какие метрики по ним изменились?"
        ),
        turns=(
            "Какие проблемы с notifications влияют на enterprise-клиентов?",
            "Понял. Какие риски для команды?",
            "Как это объяснить PO?",
            "Что с этим делать в первую очередь?",
            "А какие метрики по ним изменились?",
        ),
    ),
    EvaluationScenario(
        id="summary_negative_metric_follow_up",
        name="Summary Negative Metric Follow-Up",
        prompt=(
            "Q1: Какие проблемы с notifications влияют на enterprise-клиентов?\n"
            "Q2-Q4: follow-up без явного feature\n"
            "Q5: А можешь без метрик?"
        ),
        turns=(
            "Какие проблемы с notifications влияют на enterprise-клиентов?",
            "Понял. Какие риски для команды?",
            "Как это объяснить PO?",
            "Что с этим делать в первую очередь?",
            "А можешь без метрик?",
        ),
    ),
]


async def main() -> None:
    args = _parse_args()
    settings = get_settings()
    selected_models = args.models or [settings.default_rag_model]
    selected_scenarios = _select_scenarios(args.scenarios, args.limit_scenarios)

    engine = create_engine(settings.postgres_dsn)
    try:
        if not await database_available(engine):
            raise RuntimeError("PostgreSQL is not available. Start docker compose first.")
        await init_db(engine)
        session_factory = create_session_factory(engine)
        evaluation_service = EvaluationService(session_factory=session_factory)

        run_id = await evaluation_service.create_run(
            name=args.name or _default_run_name(),
            checklist_version=args.checklist_version,
            models=selected_models,
            scenario_count=len(selected_scenarios),
            notes=args.notes,
            metadata={
                "base_url": args.base_url,
                "top_k": args.top_k,
                "scenario_ids": [scenario.id for scenario in selected_scenarios],
            },
        )
        print(f"evaluation_run_id={run_id}")

        status = "completed"
        async with httpx.AsyncClient(
            base_url=args.base_url,
            timeout=args.timeout_seconds,
        ) as client:
            for scenario in selected_scenarios:
                for model in selected_models:
                    try:
                        data = await _run_scenario(
                            client=client,
                            scenario=scenario,
                            model=model,
                            top_k=args.top_k,
                        )
                        await evaluation_service.add_result(
                            run_id=run_id,
                            scenario_id=scenario.id,
                            scenario_name=scenario.name,
                            prompt=scenario.prompt,
                            model=model,
                            provider=data.get("provider"),
                            response=data.get("response"),
                            latency_ms=data.get("latency_ms"),
                            score_threshold=data.get("score_threshold"),
                            source_count=len(data.get("sources") or []),
                            sources=_summarize_sources(data.get("sources") or []),
                            retrieval=_build_retrieval_snapshot(data),
                            query_hints=data.get("query_hints") or {},
                            context_policy=data.get("context_policy") or {},
                            quality_flags=_build_quality_flags(scenario, data),
                        )
                        print(
                            "ok "
                            f"scenario={scenario.id} model={model} "
                            f"latency_ms={data.get('latency_ms')} "
                            f"sources={len(data.get('sources') or [])}"
                        )
                    except Exception as exc:
                        status = "failed"
                        await evaluation_service.add_result(
                            run_id=run_id,
                            scenario_id=scenario.id,
                            scenario_name=scenario.name,
                            prompt=scenario.prompt,
                            model=model,
                            error=str(exc),
                            quality_flags={"error": True},
                        )
                        print(f"error scenario={scenario.id} model={model}: {exc}")

        await evaluation_service.complete_run(run_id=run_id, status=status)
        print(f"evaluation_status={status}")
    finally:
        await engine.dispose()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RAG evaluation and persist results.")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Backend base URL.",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        help="Ollama model names. Defaults to DEFAULT_RAG_MODEL.",
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        help="Scenario ids to run. Defaults to all scenarios.",
    )
    parser.add_argument(
        "--limit-scenarios",
        type=int,
        default=None,
        help="Run only first N selected scenarios for smoke tests.",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--name", default=None)
    parser.add_argument("--checklist-version", default="RAG_EVALUATION_CHECKLIST.md")
    parser.add_argument("--notes", default=None)
    return parser.parse_args()


def _select_scenarios(
    scenario_ids: list[str] | None,
    limit: int | None,
) -> list[EvaluationScenario]:
    scenarios = SCENARIOS
    if scenario_ids:
        requested_ids = set(scenario_ids)
        scenarios = [scenario for scenario in scenarios if scenario.id in requested_ids]
        missing_ids = requested_ids - {scenario.id for scenario in scenarios}
        if missing_ids:
            raise ValueError(f"Unknown scenario ids: {sorted(missing_ids)}")
    if limit is not None:
        scenarios = scenarios[:limit]
    return scenarios


async def _run_scenario(
    *,
    client: httpx.AsyncClient,
    scenario: EvaluationScenario,
    model: str,
    top_k: int,
) -> dict[str, Any]:
    session_id: str | None = None
    data: dict[str, Any] | None = None
    turns = scenario.turns or (scenario.prompt,)
    for turn in turns:
        payload = {
            "message": turn,
            "model": model,
            "top_k": top_k,
        }
        if session_id:
            payload["session_id"] = session_id
        response = await client.post("/rag/chat", json=payload)
        response.raise_for_status()
        data = response.json()
        session_id = data.get("session_id") or session_id

    if data is None:
        raise RuntimeError(f"Scenario has no turns: {scenario.id}")
    return data


def _summarize_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": source.get("id"),
            "score": source.get("score"),
            "title": source.get("title"),
            "source_type": source.get("source_type"),
            "source_path": source.get("source_path"),
            "feature": source.get("feature") or [],
        }
        for source in sources
    ]


def _build_retrieval_snapshot(data: dict[str, Any]) -> dict[str, object]:
    retrieval = dict(data.get("retrieval") or {})
    conversation_context = data.get("conversation_context") or {}
    if conversation_context:
        retrieval["conversation_context"] = conversation_context
    return retrieval


def _build_quality_flags(
    scenario: EvaluationScenario,
    data: dict[str, Any],
) -> dict[str, object]:
    response = (data.get("response") or "").lower()
    sources = data.get("sources") or []
    query_hints = data.get("query_hints") or {}
    context_policy = data.get("context_policy") or {}
    conversation_context = data.get("conversation_context") or {}
    source_types = {
        source.get("source_type")
        for source in sources
        if source.get("source_type")
    }
    source_features = {
        feature
        for source in sources
        for feature in (source.get("feature") or [])
    }
    response_features = set(data.get("features") or [])

    flags: dict[str, object] = {
        "non_empty_response": bool(response.strip()),
        "has_sources": bool(sources),
    }

    if scenario.id == "metric_intent":
        flags["metric_intent_ok"] = query_hints.get("metric_intent") is True
        flags["has_metric_row_source"] = "metric_row" in source_types
    elif scenario.id == "negative_metric_intent":
        flags["negative_marker_ok"] = query_hints.get("metric_negative_marker") is True
        flags["numeric_sanitization_ok"] = (
            context_policy.get("numeric_line_sanitization") is True
        )
        flags["no_percent_symbol"] = "%" not in response
    elif scenario.id == "source_diversity_stress":
        flags["support_feedback_intent_ok"] = (
            query_hints.get("support_feedback_intent") is True
        )
        flags["has_support_ticket_source"] = "support_ticket" in source_types
    elif scenario.id == "technical_root_cause":
        flags["technical_root_cause_intent_ok"] = (
            query_hints.get("technical_root_cause_intent") is True
        )
    elif scenario.id == "release_notes_focus":
        flags["release_notes_intent_ok"] = query_hints.get("release_notes_intent") is True
        flags["has_release_note_source"] = "release_note" in source_types
    elif scenario.id == "no_answer_groundedness":
        flags["refusal_or_missing_data_ok"] = _contains_any(
            response,
            (
                "нет данных",
                "не хватает",
                "недостаточно",
                "нет информации",
                "контекст не предоставляет",
                "точные цифры",
                "точных цифр",
                "отсутствуют",
                "не приведены",
                "не указано",
                "не указаны",
                "в предоставленном контексте нет",
                "не предоставляет конкретной информации",
                "конкретная сумма",
                "не упоминается",
                "дополнительные данные",
                "потребовались бы",
            ),
        )
    elif scenario.id == "incident_summary":
        flags["incident_intent_ok"] = query_hints.get("incident_intent") is True
        flags["has_incident_source"] = "incident_note" in source_types
    elif scenario.id == "follow_up_continuation":
        flags["conversation_context_used"] = conversation_context.get("used") is True
        flags["follow_up_detected"] = (
            conversation_context.get("follow_up_detected") is True
        )
        flags["has_final_sources"] = (data.get("retrieval") or {}).get("final_top_k", 0) > 0
        flags["notifications_context_ok"] = (
            "notifications" in response_features
            or "notifications" in source_features
            or "notifications" in str(conversation_context.get("retrieval_query", "")).lower()
        )
    elif scenario.id == "topic_switch":
        flags["topic_switch_not_rewritten"] = conversation_context.get("used") is not True
        flags["csv_import_context_ok"] = (
            "csv_import" in response_features
            or "csv_import" in source_features
            or "csv_import" in str(conversation_context.get("retrieval_query", "")).lower()
        )
    elif scenario.id == "follow_up_action_plan":
        flags["conversation_context_used"] = conversation_context.get("used") is True
        flags["follow_up_detected"] = (
            conversation_context.get("follow_up_detected") is True
        )
        flags["notifications_context_ok"] = _has_context_feature(
            feature="notifications",
            response_features=response_features,
            source_features=source_features,
            conversation_context=conversation_context,
        )
    elif scenario.id == "explicit_topic_switch":
        flags["topic_switch_detected"] = (
            conversation_context.get("topic_switch_detected") is True
        )
        flags["conversation_context_not_used"] = conversation_context.get("used") is not True
        flags["permissions_context_ok"] = _has_context_feature(
            feature="permissions",
            response_features=response_features,
            source_features=source_features,
            conversation_context=conversation_context,
        )
    elif scenario.id == "follow_up_metric_intent":
        flags["conversation_context_used"] = conversation_context.get("used") is True
        flags["metric_intent_ok"] = query_hints.get("metric_intent") is True
        flags["has_metric_row_source"] = "metric_row" in source_types
        flags["notifications_context_ok"] = _has_context_feature(
            feature="notifications",
            response_features=response_features,
            source_features=source_features,
            conversation_context=conversation_context,
        )
    elif scenario.id == "follow_up_negative_metric":
        flags["conversation_context_used"] = conversation_context.get("used") is True
        flags["negative_marker_ok"] = query_hints.get("metric_negative_marker") is True
        flags["numeric_sanitization_ok"] = (
            context_policy.get("numeric_line_sanitization") is True
        )
        flags["no_percent_symbol"] = "%" not in response
    elif scenario.id == "follow_up_incident":
        flags["conversation_context_used"] = conversation_context.get("used") is True
        flags["incident_intent_ok"] = query_hints.get("incident_intent") is True
        flags["has_incident_source"] = "incident_note" in source_types
    elif scenario.id == "summary_long_follow_up":
        flags["summary_available"] = conversation_context.get("summary_available") is True
        flags["summary_used"] = conversation_context.get("summary_used") is True
        flags["has_final_sources"] = (data.get("retrieval") or {}).get("final_top_k", 0) > 0
        flags["notifications_context_ok"] = _has_context_feature(
            feature="notifications",
            response_features=response_features,
            source_features=source_features,
            conversation_context=conversation_context,
        )
    elif scenario.id == "summary_topic_switch":
        flags["summary_available"] = conversation_context.get("summary_available") is True
        flags["summary_not_used"] = conversation_context.get("summary_used") is not True
        flags["topic_switch_detected"] = (
            conversation_context.get("topic_switch_detected") is True
        )
        flags["permissions_context_ok"] = _has_context_feature(
            feature="permissions",
            response_features=response_features,
            source_features=source_features,
            conversation_context=conversation_context,
        )
    elif scenario.id == "summary_metric_follow_up":
        flags["summary_used"] = conversation_context.get("summary_used") is True
        flags["metric_intent_ok"] = query_hints.get("metric_intent") is True
        flags["has_metric_row_source"] = "metric_row" in source_types
        flags["notifications_context_ok"] = _has_context_feature(
            feature="notifications",
            response_features=response_features,
            source_features=source_features,
            conversation_context=conversation_context,
        )
    elif scenario.id == "summary_negative_metric_follow_up":
        flags["summary_used"] = conversation_context.get("summary_used") is True
        flags["negative_marker_ok"] = query_hints.get("metric_negative_marker") is True
        flags["numeric_sanitization_ok"] = (
            context_policy.get("numeric_line_sanitization") is True
        )
        flags["no_percent_symbol"] = "%" not in response

    return flags


def _has_context_feature(
    *,
    feature: str,
    response_features: set[str],
    source_features: set[str],
    conversation_context: dict[str, Any],
) -> bool:
    return (
        feature in response_features
        or feature in source_features
        or feature in str(conversation_context.get("retrieval_query", "")).lower()
        or feature in (conversation_context.get("carried_features") or [])
        or feature in (conversation_context.get("current_features") or [])
        or feature in (conversation_context.get("summary_features") or [])
    )


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _default_run_name() -> str:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"RAG evaluation {timestamp}"


if __name__ == "__main__":
    asyncio.run(main())
