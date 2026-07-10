from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
SCRIPT_DIR = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from app.db.base import Base  # noqa: E402
from app.services.sql_validator import validate_read_only_sql  # noqa: E402
from generate_text_to_sql_dataset_v2 import (  # noqa: E402
    DatasetExample,
    SqlIntent,
    build_schema_context,
    instruction_variants,
    intents as v2_intents,
    write_jsonl,
)


DATASET_VERSION = "text_to_sql_v3"
OUTPUT_DIR = PROJECT_ROOT / "data/text_to_sql/v3"


def support_intents() -> list[SqlIntent]:
    return [
        SqlIntent(
            id="support_recent_error_results_compact",
            split="train",
            instruction="Покажи последние evaluation results, где есть error, с названием scenario.",
            sql="SELECT run_id, scenario_id, scenario_name, error, created_at FROM evaluation_results WHERE error IS NOT NULL ORDER BY created_at DESC LIMIT 10",
            required_tables=("evaluation_results",),
            tags=("filter", "order_by", "limit", "support_error_filter"),
            required_terms=("where", "is not null", "order by", "limit"),
        ),
        SqlIntent(
            id="support_error_results_by_model_recent",
            split="train",
            instruction="Покажи последние ошибки evaluation_results по model и scenario.",
            sql="SELECT run_id, scenario_id, scenario_name, model, error, created_at FROM evaluation_results WHERE error IS NOT NULL ORDER BY created_at DESC LIMIT 10",
            required_tables=("evaluation_results",),
            tags=("filter", "order_by", "limit", "support_error_filter"),
            required_terms=("where", "is not null", "order by", "limit"),
        ),
        SqlIntent(
            id="support_avg_rag_score_by_source_type_with_count",
            split="train",
            instruction="Найди средний RAG source score по source_type и количество sources.",
            sql="SELECT source_type, ROUND(AVG(score)::numeric, 4) AS avg_score, COUNT(*) AS source_count FROM rag_source_logs WHERE source_type IS NOT NULL AND score IS NOT NULL GROUP BY source_type ORDER BY avg_score DESC LIMIT 20",
            required_tables=("rag_source_logs",),
            tags=("aggregate", "filter", "limit", "support_avg_score"),
            required_terms=("avg", "count", "where", "group by", "order by", "limit"),
        ),
        SqlIntent(
            id="support_avg_rag_score_by_source_path_with_count",
            split="train",
            instruction="Посчитай средний score по source_path для RAG sources.",
            sql="SELECT source_path, ROUND(AVG(score)::numeric, 4) AS avg_score, COUNT(*) AS source_count FROM rag_source_logs WHERE source_path IS NOT NULL AND score IS NOT NULL GROUP BY source_path ORDER BY avg_score DESC LIMIT 20",
            required_tables=("rag_source_logs",),
            tags=("aggregate", "filter", "limit", "support_avg_score"),
            required_terms=("avg", "count", "where", "group by", "order by", "limit"),
        ),
        SqlIntent(
            id="support_chat_messages_by_created_day",
            split="train",
            instruction="Посчитай chat messages по дням создания.",
            sql="SELECT DATE_TRUNC('day', created_at) AS created_day, COUNT(*) AS message_count FROM chat_messages GROUP BY created_day ORDER BY created_day DESC",
            required_tables=("chat_messages",),
            tags=("date_trunc", "aggregate", "support_date_trunc"),
            required_terms=("date_trunc", "count", "group by", "order by"),
        ),
        SqlIntent(
            id="support_rag_requests_by_created_day",
            split="train",
            instruction="Посчитай RAG requests по дням создания.",
            sql="SELECT DATE_TRUNC('day', created_at) AS created_day, COUNT(*) AS request_count FROM rag_request_logs GROUP BY created_day ORDER BY created_day DESC",
            required_tables=("rag_request_logs",),
            tags=("date_trunc", "aggregate", "support_date_trunc"),
            required_terms=("date_trunc", "count", "group by", "order by"),
        ),
        SqlIntent(
            id="support_summaries_by_updated_day",
            split="train",
            instruction="Посчитай conversation summaries по дням обновления.",
            sql="SELECT DATE_TRUNC('day', updated_at) AS updated_day, COUNT(*) AS summary_count FROM conversation_summaries GROUP BY updated_day ORDER BY updated_day DESC",
            required_tables=("conversation_summaries",),
            tags=("date_trunc", "aggregate", "support_date_trunc"),
            required_terms=("date_trunc", "count", "group by", "order by"),
        ),
    ]


def intents() -> list[SqlIntent]:
    all_intents = v2_intents() + support_intents()
    return sorted(all_intents, key=lambda item: (item.split != "train", item.id))


def examples(schema_context: str) -> list[DatasetExample]:
    generated: list[DatasetExample] = []
    for intent_index, intent in enumerate(intents(), start=1):
        for variant_index, instruction in enumerate(
            instruction_variants(intent.instruction), start=1
        ):
            generated.append(
                DatasetExample(
                    id=f"t2sql_v3_{intent_index:03d}_{variant_index}",
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
        "split_policy": "intent_level_split_with_support_intents",
        "base_dataset": "text_to_sql_v2",
        "support_focus": [
            "error filters with latest rows",
            "avg score with count and dual null filters",
            "date_trunc grouping",
        ],
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
