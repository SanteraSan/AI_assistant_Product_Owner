from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.dialects import postgresql

from app.db.base import Base
from app.db import models  # noqa: F401
from app.services.sql_validator import validate_read_only_sql


DATASET_VERSION = "text_to_sql_v1"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "data/text_to_sql/v1"


@dataclass(frozen=True)
class DatasetExample:
    id: str
    instruction: str
    input: str
    output: str
    metadata: dict[str, Any]


def build_schema_context() -> str:
    dialect = postgresql.dialect()
    lines = ["PostgreSQL schema:"]
    for table in sorted(Base.metadata.sorted_tables, key=lambda item: item.name):
        columns = ", ".join(
            f"{column.name} {column.type.compile(dialect=dialect)}"
            for column in table.columns
        )
        lines.append(f"- {table.name}({columns})")
    return "\n".join(lines)


def examples(schema_context: str) -> list[DatasetExample]:
    specs = [
        (
            "evaluation_results_by_model_latest_run",
            "Покажи количество evaluation results по model для последнего evaluation run.",
            "SELECT er.model, COUNT(*) AS result_count FROM evaluation_results er WHERE er.run_id = (SELECT id FROM evaluation_runs ORDER BY started_at DESC LIMIT 1) GROUP BY er.model ORDER BY result_count DESC",
            ("evaluation_runs", "evaluation_results"),
            ("join", "group_by", "latest_run"),
        ),
        (
            "evaluation_failures_by_scenario",
            "Покажи scenarios с количеством technical errors за все evaluation runs.",
            "SELECT scenario_id, scenario_name, COUNT(*) FILTER (WHERE error IS NOT NULL) AS technical_errors FROM evaluation_results GROUP BY scenario_id, scenario_name ORDER BY technical_errors DESC, scenario_id",
            ("evaluation_results",),
            ("aggregate", "filter"),
        ),
        (
            "slowest_scenarios_avg_latency",
            "Найди 5 самых медленных evaluation scenarios по средней latency_ms.",
            "SELECT scenario_id, scenario_name, ROUND(AVG(latency_ms)::numeric, 2) AS avg_latency_ms FROM evaluation_results WHERE latency_ms IS NOT NULL GROUP BY scenario_id, scenario_name ORDER BY avg_latency_ms DESC LIMIT 5",
            ("evaluation_results",),
            ("aggregate", "order_by", "limit"),
        ),
        (
            "latest_runs_status",
            "Покажи последние 10 evaluation runs со статусом и количеством scenarios.",
            "SELECT id, name, status, scenario_count, started_at, completed_at FROM evaluation_runs ORDER BY started_at DESC LIMIT 10",
            ("evaluation_runs",),
            ("order_by", "limit"),
        ),
        (
            "quality_flags_marker_failures",
            "Посчитай marker failures по model из evaluation_results.",
            "SELECT model, COUNT(*) FILTER (WHERE NOT COALESCE((quality_flags->>'response_has_required_markers')::boolean, TRUE)) AS marker_failures FROM evaluation_results GROUP BY model ORDER BY marker_failures DESC",
            ("evaluation_results",),
            ("jsonb", "aggregate"),
        ),
        (
            "chat_messages_recent",
            "Покажи последние 20 chat messages с role, model и created_at.",
            "SELECT session_id, role, model, created_at, LEFT(content, 120) AS content_preview FROM chat_messages ORDER BY created_at DESC LIMIT 20",
            ("chat_messages",),
            ("order_by", "limit"),
        ),
        (
            "chat_messages_by_role",
            "Посчитай chat messages по role.",
            "SELECT role, COUNT(*) AS message_count FROM chat_messages GROUP BY role ORDER BY message_count DESC",
            ("chat_messages",),
            ("aggregate", "group_by"),
        ),
        (
            "chat_sessions_activity",
            "Покажи sessions с количеством сообщений и временем последнего сообщения.",
            "SELECT cs.id AS session_id, COUNT(cm.id) AS message_count, MAX(cm.created_at) AS last_message_at FROM chat_sessions cs LEFT JOIN chat_messages cm ON cm.session_id = cs.id GROUP BY cs.id ORDER BY last_message_at DESC NULLS LAST LIMIT 20",
            ("chat_sessions", "chat_messages"),
            ("join", "aggregate"),
        ),
        (
            "conversation_summary_features",
            "Разверни features из conversation summaries и посчитай частоту каждой feature.",
            "SELECT feature, COUNT(*) AS summary_count FROM conversation_summaries cs CROSS JOIN LATERAL jsonb_array_elements_text(cs.features) AS feature GROUP BY feature ORDER BY summary_count DESC",
            ("conversation_summaries",),
            ("jsonb", "lateral", "aggregate"),
        ),
        (
            "conversation_summary_staleness",
            "Найди summaries, которые давно не обновлялись.",
            "SELECT session_id, message_count_at_update, updated_at FROM conversation_summaries ORDER BY updated_at ASC LIMIT 20",
            ("conversation_summaries",),
            ("order_by", "limit"),
        ),
        (
            "rag_request_latency_by_model",
            "Посчитай среднюю latency RAG requests по model.",
            "SELECT model, ROUND(AVG(latency_ms)::numeric, 2) AS avg_latency_ms, COUNT(*) AS request_count FROM rag_request_logs GROUP BY model ORDER BY avg_latency_ms DESC",
            ("rag_request_logs",),
            ("aggregate", "group_by"),
        ),
        (
            "rag_requests_by_feature",
            "Разверни features из RAG request logs и посчитай количество requests по feature.",
            "SELECT feature, COUNT(*) AS request_count FROM rag_request_logs r CROSS JOIN LATERAL jsonb_array_elements_text(r.features) AS feature GROUP BY feature ORDER BY request_count DESC",
            ("rag_request_logs",),
            ("jsonb", "lateral", "aggregate"),
        ),
        (
            "rag_source_type_counts",
            "Какие source_type чаще всего попадали в RAG source logs?",
            "SELECT source_type, COUNT(*) AS source_count FROM rag_source_logs GROUP BY source_type ORDER BY source_count DESC",
            ("rag_source_logs",),
            ("aggregate", "group_by"),
        ),
        (
            "rag_sources_by_request",
            "Покажи последние RAG requests вместе с количеством source logs.",
            "SELECT r.id, r.created_at, r.model, COUNT(s.id) AS source_count FROM rag_request_logs r LEFT JOIN rag_source_logs s ON s.request_log_id = r.id GROUP BY r.id, r.created_at, r.model ORDER BY r.created_at DESC LIMIT 20",
            ("rag_request_logs", "rag_source_logs"),
            ("join", "aggregate", "limit"),
        ),
        (
            "top_rag_source_titles",
            "Покажи самые частые titles среди RAG sources.",
            "SELECT title, COUNT(*) AS usage_count FROM rag_source_logs WHERE title IS NOT NULL GROUP BY title ORDER BY usage_count DESC LIMIT 10",
            ("rag_source_logs",),
            ("aggregate", "filter", "limit"),
        ),
        (
            "rag_source_scores",
            "Найди средний score по source_type в RAG source logs.",
            "SELECT source_type, ROUND(AVG(score)::numeric, 4) AS avg_score FROM rag_source_logs WHERE score IS NOT NULL GROUP BY source_type ORDER BY avg_score DESC",
            ("rag_source_logs",),
            ("aggregate", "filter"),
        ),
    ]

    generated: list[DatasetExample] = []
    instruction_variants = (
        "{instruction}",
        "Сформируй PostgreSQL SELECT: {instruction}",
        "Нужен read-only SQL для аналитики: {instruction}",
    )
    for spec_index, (example_id, instruction, sql, tables, tags) in enumerate(specs, start=1):
        for variant_index, variant in enumerate(instruction_variants, start=1):
            generated.append(
                DatasetExample(
                    id=f"t2sql_v1_{spec_index:03d}_{variant_index}",
                    instruction=variant.format(instruction=instruction),
                    input=schema_context,
                    output=sql,
                    metadata={
                        "source": "manual_seed",
                        "intent_id": example_id,
                        "required_tables": list(tables),
                        "tags": list(tags),
                    },
                )
            )

    return generated


def split_name(index: int) -> str:
    position = index + 1
    if position % 5 == 0:
        return "test"
    if position % 5 == 4:
        return "validation"
    return "train"


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    schema_context = build_schema_context()
    dataset = examples(schema_context)
    allowed_tables = {table.name for table in Base.metadata.sorted_tables}
    split_rows: dict[str, list[dict[str, Any]]] = {
        "train": [],
        "validation": [],
        "test": [],
    }
    validation_errors: list[dict[str, str]] = []

    for index, example in enumerate(dataset):
        result = validate_read_only_sql(example.output, allowed_tables=allowed_tables)
        if not result.valid:
            validation_errors.append(
                {
                    "id": example.id,
                    "error": result.error or "unknown_error",
                }
            )
        split = split_name(index)
        row = asdict(example)
        row["metadata"]["split"] = split
        split_rows[split].append(row)

    if validation_errors:
        raise RuntimeError(f"Dataset SQL validation failed: {validation_errors}")

    for split, rows in split_rows.items():
        write_jsonl(OUTPUT_DIR / f"{split}.jsonl", rows)

    manifest = {
        "dataset_version": DATASET_VERSION,
        "total_examples": len(dataset),
        "splits": {split: len(rows) for split, rows in split_rows.items()},
        "allowed_tables": sorted(allowed_tables),
        "format": {
            "instruction": "natural language analytics request",
            "input": "PostgreSQL schema context",
            "output": "single read-only PostgreSQL SELECT statement",
            "metadata": "source, required_tables, tags, split",
        },
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
