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
    instruction_variants,
    write_jsonl,
)
from generate_text_to_sql_dataset_v3 import (  # noqa: E402
    build_schema_context,
    intents as v3_intents,
)


DATASET_VERSION = "text_to_sql_v4"
OUTPUT_DIR = PROJECT_ROOT / "data/text_to_sql/v4"


def extra_support_intents() -> list[SqlIntent]:
    return [
        SqlIntent(
            id="support_latest_error_results_full_projection",
            split="train",
            instruction=(
                "Покажи последние evaluation results с error, включая model и "
                "scenario_name."
            ),
            sql="SELECT run_id, scenario_id, scenario_name, model, error, created_at FROM evaluation_results WHERE error IS NOT NULL ORDER BY created_at DESC LIMIT 20",
            required_tables=("evaluation_results",),
            tags=("filter", "order_by", "limit", "support_error_filter"),
            required_terms=("where", "is not null", "order by", "limit"),
        )
    ]


def intents() -> list[SqlIntent]:
    return sorted(
        v3_intents() + extra_support_intents(),
        key=lambda item: (item.split != "train", item.id),
    )


def examples(schema_context: str) -> list[DatasetExample]:
    generated: list[DatasetExample] = []
    for intent_index, intent in enumerate(intents(), start=1):
        for variant_index, instruction in enumerate(
            instruction_variants(intent.instruction), start=1
        ):
            generated.append(
                DatasetExample(
                    id=f"t2sql_v4_{intent_index:03d}_{variant_index}",
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
        "base_dataset": "text_to_sql_v3",
        "support_focus": [
            "full latest error projection",
            "limit 20 for latest error reports",
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
