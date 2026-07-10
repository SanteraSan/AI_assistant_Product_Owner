# Text-to-SQL Baseline 2026-07-10

## Goal

Create the first safe baseline for natural-language analytics questions against the project PostgreSQL schema.

This is the baseline before LoRA/QLoRA fine-tuning.

## Scope

Models:

- `qwen3.5:9b`
- `gemma4:12b`
- `qwen2.5-coder:7b`

Scenarios:

- `evaluation_results_by_model`
- `slowest_evaluation_scenarios`
- `recent_chat_messages`
- `rag_source_type_counts`
- `conversation_summary_count`

Evaluation checks:

- read-only SQL validation;
- destructive keyword rejection;
- allowed table validation;
- required tables present;
- required SQL terms present;
- read-only execution success;
- latency.

Artifact:

- `research/text_to_sql_baseline_latest.json`

## Summary

- `qwen3.5:9b`: 5 results, 5 valid SQL, 5 execution success, 4 required-tables hits, 4 required-terms hits, avg latency `863 ms`.
- `gemma4:12b`: 5 results, 5 valid SQL, 5 execution success, 5 required-tables hits, 5 required-terms hits, avg latency `8534 ms`.
- `qwen2.5-coder:7b`: 5 results, 5 valid SQL, 5 execution success, 5 required-tables hits, 5 required-terms hits, avg latency `5368 ms`.

## Findings

- All three models generated syntactically valid, read-only, executable PostgreSQL SQL in all scenarios.
- `qwen3.5:9b` was dramatically faster on this first small benchmark.
- `qwen3.5:9b` missed the expected evidence table in `rag_source_type_counts`: it queried `rag_request_logs.source_types` instead of `rag_source_logs.source_type`.
- `gemma4:12b` had perfect baseline quality on these checks, but was the slowest.
- `qwen2.5-coder:7b` also had perfect baseline quality and was faster than `gemma4:12b`, but slower than `qwen3.5:9b`.

## Decision

Keep all three models in the next M7 comparison layer:

- `qwen3.5:9b` as the fastest strong general baseline;
- `gemma4:12b` as a high-quality reference baseline;
- `qwen2.5-coder:7b` as the SQL-specialized baseline and likely LoRA base family.

The next step is to build a larger Text-to-SQL dataset with train/validation/test split. LoRA should be evaluated against this baseline, not assumed to be better.
