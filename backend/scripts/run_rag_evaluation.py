import argparse
import asyncio
import re
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
    tenant_id: str | None = None
    bucket_ids: tuple[str, ...] = ()
    source_types: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    source_paths: tuple[str, ...] = ()
    expected_bucket_ids: tuple[str, ...] = ()
    forbidden_bucket_ids: tuple[str, ...] = ()
    required_response_markers: tuple[str, ...] = ()
    required_marker_groups: tuple[tuple[str, ...], ...] = ()
    required_numeric_values: tuple[str, ...] = ()
    forbidden_response_markers: tuple[str, ...] = ()
    score_threshold: float | None = None
    expected_feature: str | None = None
    expected_prompt_memory_used: bool | None = None
    expected_metric_intent: bool | None = None
    expected_negative_metric_marker: bool | None = None


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
    EvaluationScenario(
        id="llm_summary_structured",
        name="LLM Structured Summary",
        prompt=(
            "Q1: Какие проблемы с notifications влияют на enterprise-клиентов?\n"
            "Q2-Q4: follow-up без явного feature\n"
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
        id="prompt_memory_budget",
        name="Prompt Memory Budget",
        prompt=(
            "Q1: Какие проблемы с notifications влияют на enterprise-клиентов?\n"
            "Q2-Q4: follow-up для накопления summary/recent memory\n"
            "Q5: А что нужно объяснить PO в первую очередь?"
        ),
        turns=(
            "Какие проблемы с notifications влияют на enterprise-клиентов?",
            "Понял. Какие риски для команды?",
            "Как это объяснить PO?",
            "Что с этим делать в первую очередь?",
            "А что нужно объяснить PO в первую очередь?",
        ),
    ),
    EvaluationScenario(
        id="memory_permissions_long_follow_up",
        name="Memory Permissions Long Follow-Up",
        prompt=(
            "Q1: Какие проблемы с permissions влияют на enterprise-клиентов?\n"
            "Q2-Q4: follow-up без явного feature\n"
            "Q5: Что нужно объяснить PO в первую очередь?"
        ),
        turns=(
            "Какие проблемы с permissions влияют на enterprise-клиентов?",
            "Понял. Какие риски для команды?",
            "Как это объяснить PO?",
            "Что с этим делать в первую очередь?",
            "Что нужно объяснить PO в первую очередь?",
        ),
        expected_feature="permissions",
        expected_prompt_memory_used=True,
    ),
    EvaluationScenario(
        id="memory_csv_import_long_follow_up",
        name="Memory CSV Import Long Follow-Up",
        prompt=(
            "Q1: Какие проблемы с csv_import влияют на enterprise-клиентов?\n"
            "Q2-Q4: follow-up без явного feature\n"
            "Q5: Что самое критичное?"
        ),
        turns=(
            "Какие проблемы с csv_import влияют на enterprise-клиентов?",
            "Понял. Какие риски для команды?",
            "Как это объяснить PO?",
            "Что с этим делать в первую очередь?",
            "Что самое критичное?",
        ),
        expected_feature="csv_import",
        expected_prompt_memory_used=True,
    ),
    EvaluationScenario(
        id="memory_explicit_topic_switch_csv",
        name="Memory Explicit Topic Switch To CSV",
        prompt=(
            "Q1: Какие проблемы с notifications влияют на enterprise-клиентов?\n"
            "Q2-Q4: follow-up без явного feature\n"
            "Q5: Ок, забудь notifications, а теперь про csv_import"
        ),
        turns=(
            "Какие проблемы с notifications влияют на enterprise-клиентов?",
            "Понял. Какие риски для команды?",
            "Как это объяснить PO?",
            "Что с этим делать в первую очередь?",
            "Ок, забудь notifications, а теперь про csv_import",
        ),
        expected_feature="csv_import",
        expected_prompt_memory_used=False,
    ),
    EvaluationScenario(
        id="memory_return_to_previous_topic",
        name="Memory Return To Previous Topic",
        prompt=(
            "Q1: Какие проблемы с notifications влияют на enterprise-клиентов?\n"
            "Q2-Q3: follow-up без явного feature\n"
            "Q4: А теперь коротко про permissions\n"
            "Q5: Вернёмся к notifications: что самое критичное?"
        ),
        turns=(
            "Какие проблемы с notifications влияют на enterprise-клиентов?",
            "Понял. Какие риски для команды?",
            "Как это объяснить PO?",
            "А теперь коротко про permissions",
            "Вернёмся к notifications: что самое критичное?",
        ),
        expected_feature="notifications",
        expected_prompt_memory_used=False,
    ),
    EvaluationScenario(
        id="memory_metric_permissions_follow_up",
        name="Memory Metric Permissions Follow-Up",
        prompt=(
            "Q1: Какие проблемы с permissions влияют на enterprise-клиентов?\n"
            "Q2-Q4: follow-up без явного feature\n"
            "Q5: А какие метрики по ним изменились?"
        ),
        turns=(
            "Какие проблемы с permissions влияют на enterprise-клиентов?",
            "Понял. Какие риски для команды?",
            "Как это объяснить PO?",
            "Что с этим делать в первую очередь?",
            "А какие метрики по ним изменились?",
        ),
        expected_feature="permissions",
        expected_prompt_memory_used=True,
        expected_metric_intent=True,
    ),
    EvaluationScenario(
        id="memory_negative_metric_permissions_follow_up",
        name="Memory Negative Metric Permissions Follow-Up",
        prompt=(
            "Q1: Какие проблемы с permissions влияют на enterprise-клиентов?\n"
            "Q2-Q4: follow-up без явного feature\n"
            "Q5: А можешь без метрик?"
        ),
        turns=(
            "Какие проблемы с permissions влияют на enterprise-клиентов?",
            "Понял. Какие риски для команды?",
            "Как это объяснить PO?",
            "Что с этим делать в первую очередь?",
            "А можешь без метрик?",
        ),
        expected_feature="permissions",
        expected_prompt_memory_used=True,
        expected_negative_metric_marker=True,
    ),
    EvaluationScenario(
        id="memory_incident_follow_up",
        name="Memory Incident Follow-Up",
        prompt=(
            "Q1: Какие проблемы с notifications влияют на enterprise-клиентов?\n"
            "Q2-Q4: follow-up без явного feature\n"
            "Q5: А что было в мартовском инциденте?"
        ),
        turns=(
            "Какие проблемы с notifications влияют на enterprise-клиентов?",
            "Понял. Какие риски для команды?",
            "Как это объяснить PO?",
            "Что с этим делать в первую очередь?",
            "А что было в мартовском инциденте?",
        ),
        expected_feature="notifications",
        expected_prompt_memory_used=True,
    ),
    EvaluationScenario(
        id="memory_release_notes_follow_up",
        name="Memory Release Notes Follow-Up",
        prompt=(
            "Q1: Какие проблемы с notifications влияют на enterprise-клиентов?\n"
            "Q2-Q4: follow-up без явного feature\n"
            "Q5: Что было в release notes?"
        ),
        turns=(
            "Какие проблемы с notifications влияют на enterprise-клиентов?",
            "Понял. Какие риски для команды?",
            "Как это объяснить PO?",
            "Что с этим делать в первую очередь?",
            "Что было в release notes?",
        ),
        expected_feature="notifications",
        expected_prompt_memory_used=True,
    ),
    EvaluationScenario(
        id="memory_short_follow_up_recent_only",
        name="Memory Short Follow-Up Recent Only",
        prompt=(
            "Q1: Какие проблемы с notifications влияют на enterprise-клиентов?\n"
            "Q2: Что самое критичное?"
        ),
        turns=(
            "Какие проблемы с notifications влияют на enterprise-клиентов?",
            "Что самое критичное?",
        ),
        expected_feature="notifications",
    ),
    EvaluationScenario(
        id="pdf_text_ingestion",
        name="PDF Text Ingestion",
        prompt="Что в PDF brief сказано про delayed Slack notifications?",
        source_types=("pdf",),
        score_threshold=0.0,
    ),
    EvaluationScenario(
        id="excel_ingestion",
        name="Excel Ingestion",
        prompt="Что Excel говорит про enterprise onboarding blockers и какую рекомендацию даёт?",
        source_types=("excel_row",),
        required_response_markers=("enterprise", "excel", "validation"),
        score_threshold=0.0,
    ),
    EvaluationScenario(
        id="docx_ingestion",
        name="DOCX Ingestion",
        prompt="Что DOCX brief говорит про enterprise onboarding handoff risk и какую рекомендацию даёт?",
        source_types=("docx",),
        source_paths=(
            "/home/santera/Projects/data/raw/docx_fixtures/product_owner_brief.docx",
        ),
        required_response_markers=("enterprise", "excel"),
        required_marker_groups=(("провер", "валидац", "validation"),),
        score_threshold=0.0,
    ),
    EvaluationScenario(
        id="image_ocr_ingestion",
        name="Image OCR Ingestion",
        prompt="Что на изображении сказано про поле Найти и кнопку Начать обучение?",
        source_types=("image_ocr",),
        source_paths=(
            "/home/santera/Projects/data/raw/docx_fixtures/just_text.png",
        ),
        required_response_markers=("найти", "начать обучение", "термин"),
        score_threshold=0.0,
    ),
    EvaluationScenario(
        id="image_digest_ingestion",
        name="Image Vision Digest Ingestion",
        prompt="Что image digest говорит про коммерческое предложение для конференц-залов и общую стоимость?",
        source_types=("image_digest",),
        source_paths=(
            "/home/santera/Projects/data/raw/docx_fixtures/tablet.png",
        ),
        required_response_markers=("коммерчес", "конференц"),
        required_numeric_values=("1416960",),
        score_threshold=0.0,
    ),
    EvaluationScenario(
        id="docx_embedded_image_digest",
        name="DOCX Embedded Image Digest",
        prompt="Что изображено на встроенной картинке в DOCX sample-with-images?",
        source_types=("image_digest",),
        source_paths=(
            "/home/santera/Projects/data/raw/docx_fixtures/sample-with-images.docx",
        ),
        required_marker_groups=(
            ("изображ", "картин", "image"),
            ("график", "диаграм"),
            ("прибыл", "profit"),
        ),
        score_threshold=0.0,
    ),
    EvaluationScenario(
        id="excel_embedded_image_digest",
        name="Excel Embedded Image Digest",
        prompt="Что изображено на встроенной картинке в Excel diagramms?",
        source_types=("image_digest",),
        source_paths=(
            "/home/santera/Projects/data/raw/excel_fixtures/diagramms.xlsx",
        ),
        required_marker_groups=(
            ("абстракт", "abstract", "декоратив"),
        ),
        score_threshold=0.0,
    ),
    EvaluationScenario(
        id="excel_chart_pareto_ingestion",
        name="Excel Chart Pareto Ingestion",
        prompt="Что native Excel chart в diagramms говорит про defect analysis Pareto?",
        source_types=("excel_chart",),
        source_paths=(
            "/home/santera/Projects/data/raw/excel_fixtures/diagramms.xlsx",
        ),
        required_marker_groups=(
            ("defect", "дефект"),
            ("pareto", "парето"),
            ("occurrences", "случа", "колич"),
        ),
        required_numeric_values=("35",),
        score_threshold=0.0,
    ),
    EvaluationScenario(
        id="excel_native_chart_ingestion",
        name="Excel Native Chart Ingestion",
        prompt="Какую цель по весу и какие первые значения показывает native Excel chart в журнале снижения веса?",
        source_types=("excel_chart",),
        source_paths=(
            "/home/santera/Projects/data/raw/excel_fixtures/diagramms2.xlsx",
        ),
        required_marker_groups=(
            ("вес", "weight"),
            ("сниж", "потер", "журнал"),
        ),
        required_numeric_values=("176",),
        score_threshold=0.0,
    ),
    EvaluationScenario(
        id="bucket_alpha_positive",
        name="Bucket Alpha Positive",
        prompt="Что нужно сделать для Alpha enterprise clients по notifications?",
        tenant_id="local_demo",
        bucket_ids=("bucket_alpha",),
        source_types=("bucket_fixture",),
        expected_bucket_ids=("bucket_alpha",),
        forbidden_bucket_ids=("bucket_beta",),
        required_response_markers=("alpha", "slack"),
        required_marker_groups=(
            ("delayed", "delivery", "доставк", "статус"),
        ),
        forbidden_response_markers=("retry banner", "email notification outage"),
        score_threshold=0.0,
    ),
    EvaluationScenario(
        id="bucket_beta_positive",
        name="Bucket Beta Positive",
        prompt="Что нужно сделать для Beta pilot clients по notifications?",
        tenant_id="local_demo",
        bucket_ids=("bucket_beta",),
        source_types=("bucket_fixture",),
        expected_bucket_ids=("bucket_beta",),
        forbidden_bucket_ids=("bucket_alpha",),
        required_response_markers=("beta", "email"),
        forbidden_response_markers=("delayed delivery status", "slack delivery visibility"),
        score_threshold=0.0,
    ),
    EvaluationScenario(
        id="bucket_no_leak_negative",
        name="Bucket No-Leak Negative",
        prompt=(
            "Что Alpha customers need for delayed Slack notifications? "
            "Отвечай только по доступному bucket."
        ),
        tenant_id="local_demo",
        bucket_ids=("bucket_beta",),
        source_types=("bucket_fixture",),
        expected_bucket_ids=("bucket_beta",),
        forbidden_bucket_ids=("bucket_alpha",),
        forbidden_response_markers=("delayed delivery status", "slack delivery visibility"),
        score_threshold=0.0,
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
        if scenario.tenant_id:
            payload["tenant_id"] = scenario.tenant_id
        if scenario.bucket_ids:
            payload["bucket_ids"] = list(scenario.bucket_ids)
        if scenario.source_types:
            payload["source_types"] = list(scenario.source_types)
        if scenario.document_ids:
            payload["document_ids"] = list(scenario.document_ids)
        if scenario.source_paths:
            payload["source_paths"] = list(scenario.source_paths)
        if scenario.score_threshold is not None:
            payload["score_threshold"] = scenario.score_threshold
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
    source_bucket_ids = {
        (source.get("metadata") or {}).get("bucket_id")
        for source in sources
        if (source.get("metadata") or {}).get("bucket_id")
    }
    source_tenant_ids = {
        (source.get("metadata") or {}).get("tenant_id")
        for source in sources
        if (source.get("metadata") or {}).get("tenant_id")
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
        prompt_memory = conversation_context.get("prompt_memory") or {}
        flags["summary_available"] = conversation_context.get("summary_available") is True
        flags["summary_not_used"] = conversation_context.get("summary_used") is not True
        flags["prompt_memory_not_used"] = prompt_memory.get("used") is not True
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
    elif scenario.id == "llm_summary_structured":
        structured_summary = conversation_context.get("summary_structured") or {}
        flags["summary_available"] = conversation_context.get("summary_available") is True
        flags["summary_used"] = conversation_context.get("summary_used") is True
        flags["summary_strategy_hybrid_or_llm"] = conversation_context.get(
            "summary_strategy"
        ) in {"hybrid", "llm"}
        flags["summary_mode_llm"] = conversation_context.get("summary_mode") in {
            "llm_structured",
            "stored_summary",
        }
        flags["summary_no_fallback"] = (
            conversation_context.get("summary_fallback_used") is not True
        )
        flags["structured_summary_ok"] = _structured_summary_ok(structured_summary)
        flags["notifications_context_ok"] = _has_context_feature(
            feature="notifications",
            response_features=response_features,
            source_features=source_features,
            conversation_context=conversation_context,
        )
    elif scenario.id == "prompt_memory_budget":
        prompt_memory = conversation_context.get("prompt_memory") or {}
        flags["prompt_memory_used"] = prompt_memory.get("used") is True
        flags["prompt_memory_budget_ok"] = int(
            prompt_memory.get("token_estimate") or 0
        ) <= int(prompt_memory.get("token_budget") or 0)
        flags["prompt_memory_has_summary"] = "summary" in (
            prompt_memory.get("included") or []
        )
        flags["prompt_memory_has_recent_user_messages"] = "recent_user_messages" in (
            prompt_memory.get("included") or []
        )
        flags["notifications_context_ok"] = _has_context_feature(
            feature="notifications",
            response_features=response_features,
            source_features=source_features,
            conversation_context=conversation_context,
        )
    elif scenario.id == "pdf_text_ingestion":
        pdf_sources = [source for source in sources if source.get("source_type") == "pdf"]
        flags["has_pdf_source"] = bool(pdf_sources)
        flags["pdf_page_metadata_ok"] = any(
            ((source.get("metadata") or {}).get("document_metadata") or {}).get(
                "page_number"
            )
            for source in pdf_sources
        )
        flags["pdf_bucket_metadata_ok"] = any(
            (source.get("metadata") or {}).get("bucket_id") for source in pdf_sources
        )
        flags["pdf_mentions_notifications"] = "notifications" in response
    elif scenario.id == "excel_ingestion":
        excel_sources = [source for source in sources if source.get("source_type") == "excel_row"]
        flags["has_excel_source"] = bool(excel_sources)
        flags["excel_sheet_metadata_ok"] = any(
            ((source.get("metadata") or {}).get("document_metadata") or {}).get(
                "sheet_name"
            )
            for source in excel_sources
        )
        flags["excel_row_metadata_ok"] = any(
            ((source.get("metadata") or {}).get("document_metadata") or {}).get(
                "excel_row_number"
            )
            for source in excel_sources
        )
        flags["excel_bucket_metadata_ok"] = any(
            (source.get("metadata") or {}).get("bucket_id") for source in excel_sources
        )
    elif scenario.id == "docx_ingestion":
        docx_sources = [source for source in sources if source.get("source_type") == "docx"]
        flags["has_docx_source"] = bool(docx_sources)
        flags["docx_block_metadata_ok"] = any(
            ((source.get("metadata") or {}).get("document_metadata") or {}).get(
                "block_type"
            )
            for source in docx_sources
        )
        flags["docx_table_or_paragraph_metadata_ok"] = any(
            ((source.get("metadata") or {}).get("document_metadata") or {}).get(
                "paragraph_index"
            )
            is not None
            or ((source.get("metadata") or {}).get("document_metadata") or {}).get(
                "table_row_index"
            )
            is not None
            for source in docx_sources
        )
        flags["docx_bucket_metadata_ok"] = any(
            (source.get("metadata") or {}).get("bucket_id") for source in docx_sources
        )
    elif scenario.id == "image_ocr_ingestion":
        image_sources = [source for source in sources if source.get("source_type") == "image_ocr"]
        flags["has_image_ocr_source"] = bool(image_sources)
        flags["image_ocr_block_metadata_ok"] = any(
            ((source.get("metadata") or {}).get("document_metadata") or {}).get(
                "block_type"
            )
            == "image_ocr"
            for source in image_sources
        )
        flags["image_ocr_dimensions_metadata_ok"] = any(
            ((source.get("metadata") or {}).get("document_metadata") or {}).get(
                "image_width"
            )
            and ((source.get("metadata") or {}).get("document_metadata") or {}).get(
                "image_height"
            )
            for source in image_sources
        )
        flags["image_ocr_engine_metadata_ok"] = any(
            ((source.get("metadata") or {}).get("document_metadata") or {}).get(
                "ocr_engine"
            )
            == "tesseract"
            for source in image_sources
        )
        flags["image_ocr_bucket_metadata_ok"] = any(
            (source.get("metadata") or {}).get("bucket_id") for source in image_sources
        )
    elif scenario.id == "image_digest_ingestion":
        image_sources = [source for source in sources if source.get("source_type") == "image_digest"]
        flags["has_image_digest_source"] = bool(image_sources)
        flags["image_digest_block_metadata_ok"] = any(
            ((source.get("metadata") or {}).get("document_metadata") or {}).get(
                "block_type"
            )
            == "image_digest"
            for source in image_sources
        )
        flags["image_digest_dimensions_metadata_ok"] = any(
            ((source.get("metadata") or {}).get("document_metadata") or {}).get(
                "image_width"
            )
            and ((source.get("metadata") or {}).get("document_metadata") or {}).get(
                "image_height"
            )
            for source in image_sources
        )
        flags["image_digest_model_metadata_ok"] = any(
            ((source.get("metadata") or {}).get("document_metadata") or {}).get(
                "vision_model"
            )
            for source in image_sources
        )
        flags["image_digest_bucket_metadata_ok"] = any(
            (source.get("metadata") or {}).get("bucket_id") for source in image_sources
        )
    elif scenario.id == "docx_embedded_image_digest":
        image_sources = [source for source in sources if source.get("source_type") == "image_digest"]
        flags["has_image_digest_source"] = bool(image_sources)
        flags["docx_parent_metadata_ok"] = any(
            ((source.get("metadata") or {}).get("document_metadata") or {}).get(
                "parent_source_type"
            )
            == "docx"
            for source in image_sources
        )
        flags["embedded_path_metadata_ok"] = any(
            ((source.get("metadata") or {}).get("document_metadata") or {}).get(
                "embedded_path"
            )
            for source in image_sources
        )
    elif scenario.id == "excel_embedded_image_digest":
        image_sources = [source for source in sources if source.get("source_type") == "image_digest"]
        flags["has_image_digest_source"] = bool(image_sources)
        flags["excel_parent_metadata_ok"] = any(
            ((source.get("metadata") or {}).get("document_metadata") or {}).get(
                "parent_source_type"
            )
            == "xlsx"
            for source in image_sources
        )
        flags["embedded_path_metadata_ok"] = any(
            ((source.get("metadata") or {}).get("document_metadata") or {}).get(
                "embedded_path"
            )
            for source in image_sources
        )
    elif scenario.id in {"excel_chart_pareto_ingestion", "excel_native_chart_ingestion"}:
        chart_sources = [source for source in sources if source.get("source_type") == "excel_chart"]
        flags["has_excel_chart_source"] = bool(chart_sources)
        flags["excel_chart_metadata_ok"] = any(
            ((source.get("metadata") or {}).get("document_metadata") or {}).get(
                "chart_type"
            )
            for source in chart_sources
        )
        flags["excel_chart_bucket_metadata_ok"] = any(
            (source.get("metadata") or {}).get("bucket_id") for source in chart_sources
        )

    if scenario.expected_bucket_ids:
        expected_bucket_ids = set(scenario.expected_bucket_ids)
        forbidden_bucket_ids = set(scenario.forbidden_bucket_ids)
        flags["all_sources_allowed_bucket"] = bool(sources) and source_bucket_ids <= expected_bucket_ids
        flags["forbidden_bucket_absent"] = not (source_bucket_ids & forbidden_bucket_ids)
        flags["bucket_metadata_ok"] = bool(source_bucket_ids)
        if scenario.tenant_id:
            flags["tenant_metadata_ok"] = source_tenant_ids == {scenario.tenant_id}
            flags["retrieval_tenant_ok"] = (data.get("retrieval") or {}).get("tenant_id") == scenario.tenant_id
        flags["retrieval_bucket_scope_ok"] = set(
            (data.get("retrieval") or {}).get("bucket_ids") or []
        ) == set(scenario.bucket_ids)

    if scenario.required_response_markers:
        flags["response_has_required_markers"] = all(
            marker.lower() in response for marker in scenario.required_response_markers
        )

    if scenario.required_marker_groups:
        flags["response_has_required_marker_groups"] = _has_required_marker_groups(
            response,
            scenario.required_marker_groups,
        )

    if scenario.required_numeric_values:
        flags["response_has_required_numeric_values"] = _has_required_numeric_values(
            response,
            scenario.required_numeric_values,
        )

    if scenario.forbidden_response_markers:
        flags["response_no_forbidden_fact"] = not _contains_any(
            response,
            tuple(marker.lower() for marker in scenario.forbidden_response_markers),
        )

    if scenario.id.startswith("memory_"):
        prompt_memory = conversation_context.get("prompt_memory") or {}
        flags["prompt_memory_budget_ok"] = int(
            prompt_memory.get("token_estimate") or 0
        ) <= int(prompt_memory.get("token_budget") or 0)

        if scenario.expected_prompt_memory_used is True:
            flags["prompt_memory_used"] = prompt_memory.get("used") is True
            flags["prompt_memory_has_recent_user_messages"] = "recent_user_messages" in (
                prompt_memory.get("included") or []
            )
        elif scenario.expected_prompt_memory_used is False:
            flags["prompt_memory_not_used"] = prompt_memory.get("used") is not True

        if scenario.expected_feature:
            flags[f"{scenario.expected_feature}_context_ok"] = _has_context_feature(
                feature=scenario.expected_feature,
                response_features=response_features,
                source_features=source_features,
                conversation_context=conversation_context,
            )

        if scenario.expected_metric_intent is True:
            flags["metric_intent_ok"] = query_hints.get("metric_intent") is True
            flags["has_metric_row_source"] = "metric_row" in source_types

        if scenario.expected_negative_metric_marker is True:
            flags["negative_marker_ok"] = (
                query_hints.get("metric_negative_marker") is True
            )
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


def _has_required_marker_groups(
    text: str,
    required_groups: tuple[tuple[str, ...], ...],
) -> bool:
    return all(
        any(marker.lower() in text for marker in marker_group)
        for marker_group in required_groups
    )


def _has_required_numeric_values(
    text: str,
    required_values: tuple[str, ...],
) -> bool:
    observed_values = _normalized_numeric_values(text)
    expected_values = {
        normalized
        for value in required_values
        if (normalized := _normalize_numeric_value(value))
    }
    return expected_values <= observed_values


def _normalized_numeric_values(text: str) -> set[str]:
    candidates = re.findall(r"(?<!\w)\d[\d\s\u00a0.,]*\d|\b\d\b", text)
    return {
        normalized
        for candidate in candidates
        if (normalized := _normalize_numeric_value(candidate))
    }


def _normalize_numeric_value(value: str) -> str:
    compact = value.replace(" ", "").replace("\u00a0", "")
    compact = re.sub(r"[^0-9,.-]", "", compact)
    compact = compact.lstrip("+-")
    if not compact or not any(character.isdigit() for character in compact):
        return ""

    separators = [index for index, character in enumerate(compact) if character in ",."]
    if not separators:
        return _normalize_integer_digits(compact)

    decimal_separator_index = _detect_decimal_separator_index(compact, separators)
    if decimal_separator_index is None:
        return _normalize_integer_digits(re.sub(r"[,.]", "", compact))

    integer_part = re.sub(r"[,.]", "", compact[:decimal_separator_index])
    fractional_part = re.sub(r"[,.]", "", compact[decimal_separator_index + 1 :])
    integer_part = _normalize_integer_digits(integer_part)
    fractional_part = fractional_part.rstrip("0")
    if not fractional_part:
        return integer_part
    return f"{integer_part}.{fractional_part}"


def _detect_decimal_separator_index(
    value: str,
    separator_indexes: list[int],
) -> int | None:
    separator_chars = {value[index] for index in separator_indexes}
    if len(separator_chars) > 1:
        return separator_indexes[-1]

    separator = value[separator_indexes[0]]
    parts = value.split(separator)
    if len(parts) > 2 and all(len(part) == 3 for part in parts[1:]):
        return None

    last_separator_index = separator_indexes[-1]
    fractional_digits = re.sub(r"\D", "", value[last_separator_index + 1 :])
    integer_digits = re.sub(r"\D", "", value[:last_separator_index])
    if len(separator_indexes) == 1 and len(fractional_digits) == 3 and 1 <= len(integer_digits) <= 3:
        return None
    return last_separator_index


def _normalize_integer_digits(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    normalized = digits.lstrip("0")
    return normalized or "0"


def _structured_summary_ok(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    summary = value.get("summary")
    return isinstance(summary, str) and bool(summary.strip())


def _default_run_name() -> str:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"RAG evaluation {timestamp}"


if __name__ == "__main__":
    asyncio.run(main())
