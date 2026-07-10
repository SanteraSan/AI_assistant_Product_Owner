# Text-to-SQL LoRA V2-V4 Iteration 2026-07-10

## Goal

Continue LoRA training beyond V1 and move from example-level memorization toward a more honest intent-level benchmark.

The key change is that V2+ uses intent-level splits. Test intents are not present in the train split.

## Dataset Versions

V2:

- total examples: `165`;
- total intents: `33`;
- train/validation/test examples: `105/30/30`;
- train/validation/test intents: `21/6/6`;
- split policy: `intent_level_split`.

V3:

- total examples: `200`;
- total intents: `40`;
- train/validation/test examples: `140/30/30`;
- adds support train intents for:
  - latest error filters;
  - average score with count and null filters;
  - `DATE_TRUNC` grouping.

V4:

- total examples: `205`;
- total intents: `41`;
- train/validation/test examples: `145/30/30`;
- adds one extra support intent for full latest error projection with `LIMIT 20`.

## Baseline

Base model on V2 test:

- valid SQL: `29/30`;
- required tables present: `29/30`;
- required terms present: `0/30`;
- normalized exact match: `0/30`;
- average latency: `485ms`;
- eval VRAM peak by `nvidia-smi`: `6528 MB`.

The base model usually picks the correct table family, but it often misses required clauses such as `ORDER BY`, `LIMIT`, exact filters, and project-specific projection choices.

## V2 LoRA

Training:

- steps: `300`;
- train examples: `105`;
- train loss: `0.0591`;
- runtime: `708.5s`;
- training VRAM peak by `nvidia-smi`: `11504 MB`.

Evaluation:

- valid SQL: `30/30`;
- required tables present: `30/30`;
- required terms present: `16/30`;
- normalized exact match: `15/30`;
- average latency: `738ms`;
- eval VRAM peak by `nvidia-smi`: `6646 MB`.

Strong intents:

- status counts;
- provider counts;
- RAG request source type JSONB expansion.

Weak intents:

- latest evaluation errors;
- average RAG source score by title;
- conversation summaries by day.

## V3 LoRA

Training:

- steps: `350`;
- train examples: `140`;
- train loss: `0.0529`;
- runtime: `850.5s`;
- training VRAM peak by `nvidia-smi`: `11491 MB`.

Evaluation:

- valid SQL: `30/30`;
- required tables present: `30/30`;
- required terms present: `25/30`;
- normalized exact match: `25/30`;
- average latency: `802ms`;
- eval VRAM peak by `nvidia-smi`: `6647 MB`.

V3 fixed:

- average RAG source score by title;
- conversation summaries by day;
- kept previously strong intents stable.

Remaining issue:

- latest evaluation errors still failed exact match.

## V4 LoRA

Training:

- steps: `350`;
- train examples: `145`;
- train loss: `0.0532`;
- runtime: `834.5s`;
- training VRAM peak by `nvidia-smi`: `11490 MB`.

Evaluation:

- valid SQL: `30/30`;
- required tables present: `30/30`;
- required terms present: `25/30`;
- normalized exact match: `25/30`;
- average latency: `812ms`;
- eval VRAM peak by `nvidia-smi`: `6647 MB`.

V4 changed the remaining failure mode:

- V3 generated `LIMIT 10` and missed `model`;
- V4 generated `WHERE error IS NOT NULL`, `ORDER BY created_at DESC`, and `LIMIT 20`;
- V4 still selected `id` instead of `model`.

This means the remaining problem is now projection precision, not SQL safety or table selection.

## Current Best Result

Best current adapter:

- `models/text_to_sql_lora/qwen2_5_coder_7b_v3_steps350` and `v4_steps350` are tied on aggregate metrics;
- V4 has a better qualitative failure mode for latest-error queries;
- V4 is the better candidate to continue from conceptually, but the current training script trains from base, not from an existing adapter.

Current best held-out score:

- valid SQL: `30/30`;
- required tables present: `30/30`;
- required terms present: `25/30`;
- normalized exact match: `25/30`.

## Decision

Stop blind training iterations at V4.

Next improvement should be V5 dataset design, not just more steps:

- add contrastive projection examples for `evaluation_results`;
- explicitly distinguish `id` vs `model` vs `scenario_name` projections;
- add projection coverage metrics to evaluation;
- make required term checking less brittle around SQL normalization, especially `IS NOT NULL`;
- optionally support adapter continuation training instead of always training from the base model.
