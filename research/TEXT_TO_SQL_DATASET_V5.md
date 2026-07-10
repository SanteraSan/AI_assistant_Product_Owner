# Text-to-SQL Dataset V5

## Goal

V5 adds projection-focused supervision and evaluation.

The previous best V3/V4 adapters reached:

- valid SQL: `30/30`;
- required tables: `30/30`;
- exact match: `25/30`;
- remaining weakness: one intent family where the model chose `id` instead of `model`.

V5 targets that weakness directly.

## Shape

- total examples: `220`;
- total intents: `44`;
- train examples: `160`;
- validation examples: `30`;
- test examples: `30`;
- train intents: `32`;
- validation intents: `6`;
- test intents: `6`;
- split policy: `intent_level_split_with_projection_support`.

## New Metadata

Each example now includes:

- `required_projection`: ordered output columns expected from the SQL query.

Examples:

- `["run_id", "scenario_id", "scenario_name", "model", "error", "created_at"]`
- `["provider", "message_count"]`
- `["source_type", "request_count"]`

## New Evaluation Metric

The evaluator now extracts generated SELECT projections with `sqlglot` and records:

- `expected_projection`;
- `generated_projection`;
- `projection_exact_match`;
- aggregate `projection_exact_match` count.

This makes errors like `id` vs `model` visible even when SQL is valid and uses the correct table.

## Support Focus

V5 adds train support intents for:

- model vs id projection contrast;
- latest evaluation error reports;
- examples where `id` is correct, so the model learns the distinction rather than always avoiding `id`.

The held-out latest-error test intent is also made explicit about the required columns:

- `run_id`;
- `scenario_id`;
- `scenario_name`;
- `model`;
- `error`;
- `created_at`.

This keeps the projection metric honest: if a column is required, the natural-language request says so.

## Decision Rule

V5 should be considered better only if it improves projection metrics on the unchanged held-out test split.

Target:

- valid SQL: keep `30/30`;
- required tables: keep `30/30`;
- projection exact match: improve over V4;
- normalized exact match: improve or at least not regress materially.
