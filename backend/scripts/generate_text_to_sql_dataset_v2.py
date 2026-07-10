from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.dialects import postgresql

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import models  # noqa: F401
from app.db.base import Base
from app.services.sql_validator import validate_read_only_sql


DATASET_VERSION = "text_to_sql_v2"
OUTPUT_DIR = PROJECT_ROOT / "data/text_to_sql/v2"


@dataclass(frozen=True)
class SqlIntent:
    id: str
    split: str
    instruction: str
    sql: str
    required_tables: tuple[str, ...]
    tags: tuple[str, ...]
    required_terms: tuple[str, ...]


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


def intents() -> list[SqlIntent]:
    return [
        SqlIntent(
            id="latest_run_results_by_model",
            split="train",
            instruction="Покажи количество evaluation results по model для последнего evaluation run.",
            sql="SELECT er.model, COUNT(*) AS result_count FROM evaluation_results er WHERE er.run_id = (SELECT id FROM evaluation_runs ORDER BY started_at DESC LIMIT 1) GROUP BY er.model ORDER BY result_count DESC",
            required_tables=("evaluation_runs", "evaluation_results"),
            tags=("aggregate", "subquery", "latest_run"),
            required_terms=("count", "group by", "order by", "limit"),
        ),
        SqlIntent(
            id="slowest_scenarios_avg_latency",
            split="train",
            instruction="Найди 5 самых медленных evaluation scenarios по средней latency_ms.",
            sql="SELECT scenario_id, scenario_name, ROUND(AVG(latency_ms)::numeric, 2) AS avg_latency_ms FROM evaluation_results WHERE latency_ms IS NOT NULL GROUP BY scenario_id, scenario_name ORDER BY avg_latency_ms DESC LIMIT 5",
            required_tables=("evaluation_results",),
            tags=("aggregate", "filter", "limit"),
            required_terms=("avg", "group by", "order by", "limit"),
        ),
        SqlIntent(
            id="latest_runs_status",
            split="train",
            instruction="Покажи последние 10 evaluation runs со статусом и количеством scenarios.",
            sql="SELECT id, name, status, scenario_count, started_at, completed_at FROM evaluation_runs ORDER BY started_at DESC LIMIT 10",
            required_tables=("evaluation_runs",),
            tags=("order_by", "limit"),
            required_terms=("order by", "limit"),
        ),
        SqlIntent(
            id="quality_flags_marker_failures",
            split="train",
            instruction="Посчитай marker failures по model из evaluation_results.",
            sql="SELECT model, COUNT(*) FILTER (WHERE NOT COALESCE((quality_flags->>'response_has_required_markers')::boolean, TRUE)) AS marker_failures FROM evaluation_results GROUP BY model ORDER BY marker_failures DESC",
            required_tables=("evaluation_results",),
            tags=("jsonb", "aggregate", "filter"),
            required_terms=("count", "filter", "quality_flags", "group by"),
        ),
        SqlIntent(
            id="chat_messages_recent",
            split="train",
            instruction="Покажи последние 20 chat messages с role, model и created_at.",
            sql="SELECT session_id, role, model, created_at, LEFT(content, 120) AS content_preview FROM chat_messages ORDER BY created_at DESC LIMIT 20",
            required_tables=("chat_messages",),
            tags=("order_by", "limit", "projection"),
            required_terms=("order by", "limit"),
        ),
        SqlIntent(
            id="chat_messages_by_role",
            split="train",
            instruction="Посчитай chat messages по role.",
            sql="SELECT role, COUNT(*) AS message_count FROM chat_messages GROUP BY role ORDER BY message_count DESC",
            required_tables=("chat_messages",),
            tags=("aggregate", "group_by"),
            required_terms=("count", "group by", "order by"),
        ),
        SqlIntent(
            id="chat_sessions_activity",
            split="train",
            instruction="Покажи sessions с количеством сообщений и временем последнего сообщения.",
            sql="SELECT cs.id AS session_id, COUNT(cm.id) AS message_count, MAX(cm.created_at) AS last_message_at FROM chat_sessions cs LEFT JOIN chat_messages cm ON cm.session_id = cs.id GROUP BY cs.id ORDER BY last_message_at DESC NULLS LAST LIMIT 20",
            required_tables=("chat_sessions", "chat_messages"),
            tags=("join", "aggregate", "limit"),
            required_terms=("left join", "count", "max", "group by", "limit"),
        ),
        SqlIntent(
            id="conversation_summary_features",
            split="train",
            instruction="Разверни features из conversation summaries и посчитай частоту каждой feature.",
            sql="SELECT feature, COUNT(*) AS summary_count FROM conversation_summaries cs CROSS JOIN LATERAL jsonb_array_elements_text(cs.features) AS feature GROUP BY feature ORDER BY summary_count DESC",
            required_tables=("conversation_summaries",),
            tags=("jsonb", "lateral", "aggregate"),
            required_terms=("cross join lateral", "jsonb_array_elements_text", "group by"),
        ),
        SqlIntent(
            id="conversation_summary_staleness",
            split="train",
            instruction="Найди summaries, которые давно не обновлялись.",
            sql="SELECT session_id, message_count_at_update, updated_at FROM conversation_summaries ORDER BY updated_at ASC LIMIT 20",
            required_tables=("conversation_summaries",),
            tags=("order_by", "limit"),
            required_terms=("order by", "limit"),
        ),
        SqlIntent(
            id="rag_request_latency_by_model",
            split="train",
            instruction="Посчитай среднюю latency RAG requests по model.",
            sql="SELECT model, ROUND(AVG(latency_ms)::numeric, 2) AS avg_latency_ms, COUNT(*) AS request_count FROM rag_request_logs GROUP BY model ORDER BY avg_latency_ms DESC",
            required_tables=("rag_request_logs",),
            tags=("aggregate", "group_by"),
            required_terms=("avg", "count", "group by", "order by"),
        ),
        SqlIntent(
            id="rag_requests_by_feature",
            split="train",
            instruction="Разверни features из RAG request logs и посчитай количество requests по feature.",
            sql="SELECT feature, COUNT(*) AS request_count FROM rag_request_logs r CROSS JOIN LATERAL jsonb_array_elements_text(r.features) AS feature GROUP BY feature ORDER BY request_count DESC",
            required_tables=("rag_request_logs",),
            tags=("jsonb", "lateral", "aggregate"),
            required_terms=("cross join lateral", "jsonb_array_elements_text", "group by"),
        ),
        SqlIntent(
            id="rag_source_type_counts",
            split="train",
            instruction="Какие source_type чаще всего попадали в RAG source logs?",
            sql="SELECT source_type, COUNT(*) AS source_count FROM rag_source_logs GROUP BY source_type ORDER BY source_count DESC",
            required_tables=("rag_source_logs",),
            tags=("aggregate", "group_by"),
            required_terms=("count", "group by", "order by"),
        ),
        SqlIntent(
            id="rag_sources_by_request",
            split="train",
            instruction="Покажи последние RAG requests вместе с количеством source logs.",
            sql="SELECT r.id, r.created_at, r.model, COUNT(s.id) AS source_count FROM rag_request_logs r LEFT JOIN rag_source_logs s ON s.request_log_id = r.id GROUP BY r.id, r.created_at, r.model ORDER BY r.created_at DESC LIMIT 20",
            required_tables=("rag_request_logs", "rag_source_logs"),
            tags=("join", "aggregate", "limit"),
            required_terms=("left join", "count", "group by", "order by", "limit"),
        ),
        SqlIntent(
            id="top_rag_source_titles",
            split="train",
            instruction="Покажи самые частые titles среди RAG sources.",
            sql="SELECT title, COUNT(*) AS usage_count FROM rag_source_logs WHERE title IS NOT NULL GROUP BY title ORDER BY usage_count DESC LIMIT 10",
            required_tables=("rag_source_logs",),
            tags=("aggregate", "filter", "limit"),
            required_terms=("where", "count", "group by", "order by", "limit"),
        ),
        SqlIntent(
            id="rag_source_scores",
            split="train",
            instruction="Найди средний score по source_type в RAG source logs.",
            sql="SELECT source_type, ROUND(AVG(score)::numeric, 4) AS avg_score FROM rag_source_logs WHERE score IS NOT NULL GROUP BY source_type ORDER BY avg_score DESC",
            required_tables=("rag_source_logs",),
            tags=("aggregate", "filter"),
            required_terms=("avg", "where", "group by", "order by"),
        ),
        SqlIntent(
            id="request_logs_score_thresholds",
            split="train",
            instruction="Покажи распределение RAG requests по score_threshold.",
            sql="SELECT score_threshold, COUNT(*) AS request_count FROM rag_request_logs GROUP BY score_threshold ORDER BY score_threshold NULLS LAST",
            required_tables=("rag_request_logs",),
            tags=("aggregate", "nullable_order"),
            required_terms=("count", "group by", "order by"),
        ),
        SqlIntent(
            id="evaluation_models_per_run",
            split="train",
            instruction="Разверни список models в evaluation_runs и посчитай, как часто каждая model встречалась.",
            sql="SELECT model, COUNT(*) AS run_count FROM evaluation_runs er CROSS JOIN LATERAL jsonb_array_elements_text(er.models) AS model GROUP BY model ORDER BY run_count DESC",
            required_tables=("evaluation_runs",),
            tags=("jsonb", "lateral", "aggregate"),
            required_terms=("cross join lateral", "jsonb_array_elements_text", "group by"),
        ),
        SqlIntent(
            id="requests_with_high_prompt_tokens",
            split="train",
            instruction="Найди RAG requests, где prompt_tokens_estimate больше 2000.",
            sql="SELECT id, message, model, prompt_tokens_estimate, created_at FROM rag_request_logs WHERE prompt_tokens_estimate > 2000 ORDER BY created_at DESC LIMIT 20",
            required_tables=("rag_request_logs",),
            tags=("filter", "order_by", "limit"),
            required_terms=("where", "order by", "limit"),
        ),
        SqlIntent(
            id="chat_latency_by_model",
            split="train",
            instruction="Посчитай среднюю latency chat messages по model.",
            sql="SELECT model, ROUND(AVG(latency_ms)::numeric, 2) AS avg_latency_ms, COUNT(*) AS message_count FROM chat_messages WHERE latency_ms IS NOT NULL GROUP BY model ORDER BY avg_latency_ms DESC",
            required_tables=("chat_messages",),
            tags=("aggregate", "filter"),
            required_terms=("avg", "where", "group by", "order by"),
        ),
        SqlIntent(
            id="rag_sources_missing_title",
            split="train",
            instruction="Посчитай RAG sources без title по source_type.",
            sql="SELECT source_type, COUNT(*) AS missing_title_count FROM rag_source_logs WHERE title IS NULL GROUP BY source_type ORDER BY missing_title_count DESC",
            required_tables=("rag_source_logs",),
            tags=("aggregate", "null_filter"),
            required_terms=("where", "is null", "group by", "order by"),
        ),
        SqlIntent(
            id="evaluation_error_rate_by_model",
            split="train",
            instruction="Посчитай error rate по model в evaluation_results.",
            sql="SELECT model, COUNT(*) AS total_results, COUNT(*) FILTER (WHERE error IS NOT NULL) AS error_count, ROUND((COUNT(*) FILTER (WHERE error IS NOT NULL)::numeric / NULLIF(COUNT(*), 0)) * 100, 2) AS error_rate_percent FROM evaluation_results GROUP BY model ORDER BY error_rate_percent DESC",
            required_tables=("evaluation_results",),
            tags=("aggregate", "filter", "ratio"),
            required_terms=("filter", "nullif", "group by", "order by"),
        ),
        SqlIntent(
            id="validation_recent_runs",
            split="validation",
            instruction="Покажи последние 5 completed evaluation runs.",
            sql="SELECT id, name, started_at, completed_at FROM evaluation_runs WHERE status = 'completed' ORDER BY completed_at DESC LIMIT 5",
            required_tables=("evaluation_runs",),
            tags=("filter", "order_by", "limit"),
            required_terms=("where", "order by", "limit"),
        ),
        SqlIntent(
            id="validation_rag_source_count_per_request",
            split="validation",
            instruction="Посчитай количество source logs для каждого RAG request.",
            sql="SELECT request_log_id, COUNT(*) AS source_log_count FROM rag_source_logs GROUP BY request_log_id ORDER BY source_log_count DESC LIMIT 20",
            required_tables=("rag_source_logs",),
            tags=("aggregate", "limit"),
            required_terms=("count", "group by", "order by", "limit"),
        ),
        SqlIntent(
            id="validation_summary_message_counts",
            split="validation",
            instruction="Покажи summaries с самым большим message_count_at_update.",
            sql="SELECT session_id, message_count_at_update, updated_at FROM conversation_summaries ORDER BY message_count_at_update DESC LIMIT 10",
            required_tables=("conversation_summaries",),
            tags=("order_by", "limit"),
            required_terms=("order by", "limit"),
        ),
        SqlIntent(
            id="validation_rag_collection_counts",
            split="validation",
            instruction="Посчитай RAG requests по collection.",
            sql="SELECT collection, COUNT(*) AS request_count FROM rag_request_logs GROUP BY collection ORDER BY request_count DESC",
            required_tables=("rag_request_logs",),
            tags=("aggregate", "group_by"),
            required_terms=("count", "group by", "order by"),
        ),
        SqlIntent(
            id="validation_sources_by_feature",
            split="validation",
            instruction="Разверни feature у RAG source logs и посчитай частоту.",
            sql="SELECT feature, COUNT(*) AS source_count FROM rag_source_logs rs CROSS JOIN LATERAL jsonb_array_elements_text(rs.feature) AS feature GROUP BY feature ORDER BY source_count DESC",
            required_tables=("rag_source_logs",),
            tags=("jsonb", "lateral", "aggregate"),
            required_terms=("cross join lateral", "jsonb_array_elements_text", "group by"),
        ),
        SqlIntent(
            id="validation_sessions_without_messages",
            split="validation",
            instruction="Найди chat sessions без сообщений.",
            sql="SELECT cs.id, cs.title, cs.created_at FROM chat_sessions cs LEFT JOIN chat_messages cm ON cm.session_id = cs.id WHERE cm.id IS NULL ORDER BY cs.created_at DESC LIMIT 20",
            required_tables=("chat_sessions", "chat_messages"),
            tags=("join", "null_filter", "limit"),
            required_terms=("left join", "is null", "order by", "limit"),
        ),
        SqlIntent(
            id="test_evaluation_runs_by_status",
            split="test",
            instruction="Посчитай evaluation runs по status.",
            sql="SELECT status, COUNT(*) AS run_count FROM evaluation_runs GROUP BY status ORDER BY run_count DESC",
            required_tables=("evaluation_runs",),
            tags=("aggregate", "group_by"),
            required_terms=("count", "group by", "order by"),
        ),
        SqlIntent(
            id="test_chat_provider_counts",
            split="test",
            instruction="Посчитай chat messages по provider.",
            sql="SELECT provider, COUNT(*) AS message_count FROM chat_messages GROUP BY provider ORDER BY message_count DESC",
            required_tables=("chat_messages",),
            tags=("aggregate", "group_by"),
            required_terms=("count", "group by", "order by"),
        ),
        SqlIntent(
            id="test_rag_requests_by_source_type",
            split="test",
            instruction="Разверни source_types из RAG request logs и посчитай requests по source_type.",
            sql="SELECT source_type, COUNT(*) AS request_count FROM rag_request_logs r CROSS JOIN LATERAL jsonb_array_elements_text(r.source_types) AS source_type GROUP BY source_type ORDER BY request_count DESC",
            required_tables=("rag_request_logs",),
            tags=("jsonb", "lateral", "aggregate"),
            required_terms=("cross join lateral", "jsonb_array_elements_text", "group by"),
        ),
        SqlIntent(
            id="test_evaluation_latest_errors",
            split="test",
            instruction="Покажи последние evaluation results с error.",
            sql="SELECT run_id, scenario_id, scenario_name, model, error, created_at FROM evaluation_results WHERE error IS NOT NULL ORDER BY created_at DESC LIMIT 20",
            required_tables=("evaluation_results",),
            tags=("filter", "order_by", "limit"),
            required_terms=("where", "is not null", "order by", "limit"),
        ),
        SqlIntent(
            id="test_rag_source_avg_score_by_title",
            split="test",
            instruction="Найди средний score по title для RAG sources.",
            sql="SELECT title, ROUND(AVG(score)::numeric, 4) AS avg_score, COUNT(*) AS source_count FROM rag_source_logs WHERE title IS NOT NULL AND score IS NOT NULL GROUP BY title ORDER BY avg_score DESC LIMIT 20",
            required_tables=("rag_source_logs",),
            tags=("aggregate", "filter", "limit"),
            required_terms=("avg", "count", "where", "group by", "order by", "limit"),
        ),
        SqlIntent(
            id="test_conversation_summaries_by_day",
            split="test",
            instruction="Посчитай conversation summaries по дням создания.",
            sql="SELECT DATE_TRUNC('day', created_at) AS created_day, COUNT(*) AS summary_count FROM conversation_summaries GROUP BY created_day ORDER BY created_day DESC",
            required_tables=("conversation_summaries",),
            tags=("date_trunc", "aggregate"),
            required_terms=("date_trunc", "count", "group by", "order by"),
        ),
    ]


def instruction_variants(instruction: str) -> tuple[str, ...]:
    return (
        instruction,
        f"Сформируй PostgreSQL SELECT: {instruction}",
        f"Нужен read-only SQL для аналитики: {instruction}",
        f"Напиши безопасный SQL только на чтение: {instruction}",
        f"Сделай запрос для отчета: {instruction}",
    )


def examples(schema_context: str) -> list[DatasetExample]:
    generated: list[DatasetExample] = []
    for intent_index, intent in enumerate(intents(), start=1):
        for variant_index, instruction in enumerate(
            instruction_variants(intent.instruction), start=1
        ):
            generated.append(
                DatasetExample(
                    id=f"t2sql_v2_{intent_index:03d}_{variant_index}",
                    instruction=instruction,
                    input=schema_context,
                    output=intent.sql,
                    metadata={
                        "source": "manual_seed",
                        "intent_id": intent.id,
                        "required_tables": list(intent.required_tables),
                        "required_terms": list(intent.required_terms),
                        "tags": list(intent.tags),
                        "split": intent.split,
                    },
                )
            )
    return generated


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

    for example in dataset:
        result = validate_read_only_sql(example.output, allowed_tables=allowed_tables)
        if not result.valid:
            validation_errors.append(
                {
                    "id": example.id,
                    "error": result.error or "unknown_error",
                }
            )
        split_rows[example.metadata["split"]].append(asdict(example))

    if validation_errors:
        raise RuntimeError(f"Dataset SQL validation failed: {validation_errors}")

    for split, rows in split_rows.items():
        write_jsonl(OUTPUT_DIR / f"{split}.jsonl", rows)

    intent_counts: dict[str, int] = {"train": 0, "validation": 0, "test": 0}
    for intent in intents():
        intent_counts[intent.split] += 1

    manifest = {
        "dataset_version": DATASET_VERSION,
        "total_examples": len(dataset),
        "total_intents": len(intents()),
        "splits": {split: len(rows) for split, rows in split_rows.items()},
        "intent_splits": intent_counts,
        "split_policy": "intent_level_split",
        "allowed_tables": sorted(allowed_tables),
        "format": {
            "instruction": "natural language analytics request",
            "input": "PostgreSQL schema context",
            "output": "single read-only PostgreSQL SELECT statement",
            "metadata": "source, intent_id, required_tables, required_terms, tags, split",
        },
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
