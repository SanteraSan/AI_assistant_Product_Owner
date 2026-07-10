# Text-to-SQL Dataset V1

## Goal

Prepare the first versioned dataset for `M7: LoRA Text-to-SQL Fine-Tuning`.

The dataset is intentionally small but structured. It is designed for the first LoRA/QLoRA spike, not for final production-grade fine-tuning.

## Location

- `data/text_to_sql/v1/train.jsonl`
- `data/text_to_sql/v1/validation.jsonl`
- `data/text_to_sql/v1/test.jsonl`
- `data/text_to_sql/v1/manifest.json`

## Format

Each JSONL row contains:

- `id`: stable example id;
- `instruction`: natural language analytics request;
- `input`: PostgreSQL schema context;
- `output`: one read-only PostgreSQL `SELECT` statement;
- `metadata`: source, intent id, required tables, tags and split.

## Dataset Shape

- Total examples: `48`
- Train: `30`
- Validation: `9`
- Test: `9`

## Covered SQL Patterns

- simple `SELECT`;
- `JOIN`;
- `LEFT JOIN`;
- `GROUP BY`;
- filtered aggregates;
- `ORDER BY`;
- `LIMIT`;
- CTE-friendly examples;
- JSONB array expansion via `jsonb_array_elements_text`;
- lateral joins;
- latency and quality analytics over evaluation logs;
- chat/session analytics;
- RAG source usage analytics.

## Quality Checks

The generator validates every `output` query with `validate_read_only_sql`:

- one SQL statement only;
- only `SELECT` / `WITH ... SELECT`;
- destructive keywords rejected;
- referenced tables must exist in SQLAlchemy metadata;
- CTE aliases are allowed and not treated as external tables.

Checks passed:

- dataset generation: `48` examples;
- SQL validation: `0` failures;
- script compile: passed;
- full backend tests after dataset generation: `65 passed`.

## Next Step

Use this dataset for the first LoRA/QLoRA training spike. After the first training/evaluation loop, expand V2 with more paraphrases, harder joins and negative/safety examples if needed.
