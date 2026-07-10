# Text-to-SQL LoRA V5 Projection Evaluation

## Goal

V5 focuses on output projection quality.

The previous best V4 adapter produced valid SQL and selected the right tables, but failed one held-out intent family by choosing the wrong output columns. The important failure was `model` vs `id` / missing `model`.

## Changes

- Dataset V5 adds `required_projection` to every example.
- Evaluation now extracts SELECT output columns through `sqlglot`.
- New per-example fields:
  - `expected_projection`;
  - `generated_projection`;
  - `projection_exact_match`.
- New aggregate fields:
  - `projection_examples`;
  - `projection_exact_match`.
- Required-term checks now inspect both raw SQL and normalized SQL.

## Dataset V5

- total examples: `220`;
- train examples: `160`;
- validation examples: `30`;
- test examples: `30`;
- total intents: `44`;
- train intents: `32`;
- validation intents: `6`;
- test intents: `6`.

The held-out latest-error request now explicitly lists the expected columns. This keeps projection evaluation fair: required columns should be stated by the natural-language request.

## Base Model Baseline

Model: `Qwen/Qwen2.5-Coder-7B-Instruct`

- valid SQL: `29/30`;
- required tables: `29/30`;
- required terms: `0/30`;
- projection exact match: `17/30`;
- normalized exact match: `0/30`;
- average latency: `543ms`;
- eval VRAM peak by `nvidia-smi`: `6528 MB`.

## V5 LoRA Training

Adapter: `models/text_to_sql_lora/qwen2_5_coder_7b_v5_projection_steps400`

- steps: `400`;
- max length: `768`;
- LoRA rank/alpha: `8/16`;
- train examples: `160`;
- validation examples: `30`;
- train runtime: `970.3921s`;
- train loss: `0.0483`;
- epoch: `10.0`;
- training VRAM peak by `nvidia-smi`: `11541 MB`.

## V5 LoRA Evaluation

- valid SQL: `30/30`;
- required tables: `30/30`;
- required terms: `30/30`;
- projection exact match: `30/30`;
- normalized exact match: `30/30`;
- average latency: `809ms`;
- eval VRAM peak by `nvidia-smi`: `6650 MB`.

## Interpretation

The adapter now passes the held-out V5 projection benchmark completely.

The important engineering point is that the metric changed the shape of the work: instead of adding blind training steps, the dataset and evaluator were improved to measure the exact failure mode. After the natural-language request and expected projection were made consistent, the LoRA adapter learned the intended Text-to-SQL behavior cleanly.
