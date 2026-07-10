# Text-to-SQL LoRA Evaluation 2026-07-10

## Goal

Evaluate the local Text-to-SQL LoRA smoke adapter against the dataset V1 test split and compare it with the same Hugging Face base model.

This evaluation checks the fine-tuning pipeline and early signal. It does not claim that the 5-step adapter is a final model.

## Evaluation Setup

- Base model: `Qwen/Qwen2.5-Coder-7B-Instruct`
- Adapter: `models/text_to_sql_lora/qwen2_5_coder_7b_v1_smoke_left`
- Dataset: `data/text_to_sql/v1/test.jsonl`
- Test examples: `9`
- Quantization: 4-bit NF4
- SQL checks:
  - extract SQL from model response;
  - validate read-only SQL with `sqlglot`;
  - reject unsafe or non-SELECT statements;
  - check required tables from dataset metadata;
  - compare normalized SQL with expected SQL.

## Harness Fix

The first evaluation run exposed a prompt handling issue:

- `max_length=512` with default right truncation could cut off the question and assistant marker;
- this made the model continue from schema/prompt fragments rather than answer the actual instruction.

Fix:

- set `tokenizer.truncation_side = "left"` in both training and evaluation scripts;
- this keeps the end of the sequence: user question, assistant marker, and target SQL for training.

## Results

Corrected base-only evaluation:

- valid SQL: `8/9`;
- required tables present: `9/9`;
- normalized exact match: `0/9`;
- average latency: `758ms`.

Corrected 5-step LoRA smoke adapter evaluation:

- valid SQL: `9/9`;
- required tables present: `9/9`;
- normalized exact match: `0/9`;
- average latency: `1140ms`.

The adapter improved syntactic validity in this small test from `8/9` to `9/9`, while latency increased. Exact-match stayed at `0/9`, which is acceptable for a smoke adapter but not acceptable for a final Text-to-SQL model.

## Qualitative Findings

The generated SQL is often directionally correct:

- chooses the correct table family;
- produces read-only statements;
- uses aggregation, grouping, joins, CTEs, and JSONB functions.

The main quality gaps:

- generated SQL often differs semantically from the target;
- exact expected clauses are frequently missing, especially `ORDER BY`, `LIMIT`, and specific JSONB expressions;
- the adapter is too small/short-trained to learn the project-specific SQL style;
- exact-match is too strict as the only quality metric, but it is useful as a regression gate.

## Decision

Stage 8 confirms that local LoRA training and evaluation are technically viable:

- 7B QLoRA trains locally;
- adapter loading works;
- test split evaluation works;
- SQL guardrails catch invalid output;
- prompt truncation bug is fixed.

Next model-quality step:

- run a longer 7B LoRA experiment with corrected truncation;
- keep evaluation separate from training to avoid VRAM spikes;
- add semantic checks beyond exact match, such as required terms, grouping/order/limit checks, and optional read-only DB execution;
- expand dataset V2 with more paraphrases and harder JSONB/join examples.
