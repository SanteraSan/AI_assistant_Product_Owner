from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import asyncpg

from app.core.config import get_settings
from app.db.base import Base
from app.db import models  # noqa: F401
from app.services.ollama_client import OllamaClient
from app.services.sql_validator import extract_sql_from_response, validate_read_only_sql


DEFAULT_MODELS = ("qwen3.5:9b", "gemma4:12b", "qwen2.5-coder:7b")
DEFAULT_OUTPUT_PATH = Path("../research/text_to_sql_baseline_latest.json")


@dataclass(frozen=True)
class TextToSqlScenario:
    id: str
    question: str
    required_tables: tuple[str, ...]
    required_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class TextToSqlResult:
    scenario_id: str
    model: str
    latency_ms: int
    response: str
    extracted_sql: str
    validation_valid: bool
    validation_error: str | None
    tables: list[str]
    required_tables_present: bool
    required_terms_present: bool
    execution_success: bool
    execution_error: str | None
    row_count: int | None


SCENARIOS = (
    TextToSqlScenario(
        id="evaluation_results_by_model",
        question=(
            "Покажи количество evaluation results по model для последнего "
            "evaluation run."
        ),
        required_tables=("evaluation_runs", "evaluation_results"),
        required_terms=("count", "group by"),
    ),
    TextToSqlScenario(
        id="slowest_evaluation_scenarios",
        question=(
            "Найди 5 самых медленных evaluation scenarios по средней latency_ms "
            "за все runs."
        ),
        required_tables=("evaluation_results",),
        required_terms=("avg", "order by", "limit"),
    ),
    TextToSqlScenario(
        id="recent_chat_messages",
        question="Покажи последние 10 chat messages с session_id, role, model и created_at.",
        required_tables=("chat_messages",),
        required_terms=("order by", "limit"),
    ),
    TextToSqlScenario(
        id="rag_source_type_counts",
        question=(
            "Посчитай, какие source_type чаще всего попадали в RAG source logs."
        ),
        required_tables=("rag_source_logs",),
        required_terms=("count", "group by"),
    ),
    TextToSqlScenario(
        id="conversation_summary_count",
        question="Посчитай количество conversation summaries по features.",
        required_tables=("conversation_summaries",),
        required_terms=("count",),
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Text-to-SQL baseline evaluation.")
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def build_schema_context() -> str:
    lines = ["PostgreSQL schema:"]
    for table in sorted(Base.metadata.sorted_tables, key=lambda item: item.name):
        columns = ", ".join(
            f"{column.name} {column.type}" for column in table.columns
        )
        lines.append(f"- {table.name}({columns})")
    return "\n".join(lines)


def build_prompt(*, schema_context: str, scenario: TextToSqlScenario) -> str:
    return f"""Ты генерируешь безопасный PostgreSQL SQL для аналитики.

Правила:
- Верни только один SQL statement.
- Разрешены только SELECT или WITH ... SELECT.
- Нельзя INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE.
- Используй только таблицы из схемы.
- Не добавляй markdown, комментарии или объяснения.

{schema_context}

Вопрос:
{scenario.question}

SQL:"""


async def run_scenario(
    *,
    client: OllamaClient,
    model: str,
    scenario: TextToSqlScenario,
    schema_context: str,
    allowed_tables: set[str],
    execute: bool,
) -> TextToSqlResult:
    started_at = perf_counter()
    result = await client.generate(
        model=model,
        prompt=build_prompt(schema_context=schema_context, scenario=scenario),
        think=False,
        options={"temperature": 0.0},
    )
    latency_ms = int((perf_counter() - started_at) * 1000)
    response = str(result.get("response", ""))
    extracted_sql = extract_sql_from_response(response)
    validation = validate_read_only_sql(extracted_sql, allowed_tables=allowed_tables)
    execution_success = False
    execution_error: str | None = None
    row_count: int | None = None
    if execute and validation.valid and validation.normalized_sql:
        execution_success, execution_error, row_count = await execute_sql(
            validation.normalized_sql
        )

    normalized_sql_for_checks = (validation.normalized_sql or extracted_sql).lower()
    return TextToSqlResult(
        scenario_id=scenario.id,
        model=model,
        latency_ms=latency_ms,
        response=response,
        extracted_sql=extracted_sql,
        validation_valid=validation.valid,
        validation_error=validation.error,
        tables=validation.tables,
        required_tables_present=set(scenario.required_tables).issubset(validation.tables),
        required_terms_present=all(
            term.lower() in normalized_sql_for_checks for term in scenario.required_terms
        ),
        execution_success=execution_success,
        execution_error=execution_error,
        row_count=row_count,
    )


async def execute_sql(sql: str) -> tuple[bool, str | None, int | None]:
    settings = get_settings()
    connection = await asyncpg.connect(_asyncpg_dsn(settings.postgres_dsn))
    try:
        async with connection.transaction(readonly=True):
            records = await connection.fetch(sql, timeout=10)
            return True, None, len(records)
    except Exception as exc:
        return False, str(exc), None
    finally:
        await connection.close()


def summarize(results: list[TextToSqlResult]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for model in sorted({result.model for result in results}):
        model_results = [result for result in results if result.model == model]
        summary[model] = {
            "results": len(model_results),
            "valid_sql": sum(result.validation_valid for result in model_results),
            "execution_success": sum(result.execution_success for result in model_results),
            "required_tables_present": sum(
                result.required_tables_present for result in model_results
            ),
            "required_terms_present": sum(
                result.required_terms_present for result in model_results
            ),
            "avg_latency_ms": round(
                sum(result.latency_ms for result in model_results) / len(model_results)
            ),
        }
    return summary


def _asyncpg_dsn(postgres_dsn: str) -> str:
    return postgres_dsn.replace("postgresql+asyncpg://", "postgresql://", 1)


async def main_async(args: argparse.Namespace) -> None:
    settings = get_settings()
    schema_context = build_schema_context()
    allowed_tables = {table.name for table in Base.metadata.sorted_tables}
    client = OllamaClient(
        base_url=settings.ollama_base_url,
        timeout_seconds=args.timeout_seconds,
    )
    results: list[TextToSqlResult] = []
    try:
        for scenario in SCENARIOS:
            for model in args.models:
                result = await run_scenario(
                    client=client,
                    model=model,
                    scenario=scenario,
                    schema_context=schema_context,
                    allowed_tables=allowed_tables,
                    execute=args.execute,
                )
                results.append(result)
                print(
                    "ok "
                    f"scenario={scenario.id} model={model} "
                    f"valid={result.validation_valid} "
                    f"executed={result.execution_success} "
                    f"latency_ms={result.latency_ms}"
                )
    finally:
        await client.aclose()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "models": args.models,
        "execute": args.execute,
        "scenarios": [asdict(scenario) for scenario in SCENARIOS],
        "summary": summarize(results),
        "results": [asdict(result) for result in results],
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"output={output_path}")
    print("summary=" + json.dumps(payload["summary"], ensure_ascii=False))


def main() -> None:
    asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    main()
