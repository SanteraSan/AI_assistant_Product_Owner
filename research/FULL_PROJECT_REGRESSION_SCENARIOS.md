# Full Project Regression Scenarios

Goal: validate the whole product flow without running every scenario on every model.

This is intentionally not a Cartesian product. Each model is tested where it matters:

- core chat/RAG/context behavior: all candidate chat models;
- summarization and long-memory behavior: `qwen3.5:9b`;
- document-heavy behavior: the best document model chosen by `DOCUMENT_ONLY_REGRESSION_SCENARIOS.md`.

The long multi-turn user journey is intentionally left for a later stage.

## Stage A: Core Chat / RAG / Context, All Models

Models:

- `gemma4:12b`
- `qwen3.5:9b`
- `qwen3:14b`

Scenarios:

```text
metric_intent
negative_metric_intent
general_po_summary
source_diversity_stress
technical_root_cause
release_notes_focus
no_answer_groundedness
incident_summary
follow_up_continuation
topic_switch
follow_up_action_plan
explicit_topic_switch
follow_up_metric_intent
follow_up_negative_metric
follow_up_incident
bucket_alpha_positive
bucket_beta_positive
bucket_no_leak_negative
```

Command:

```bash
cd /home/santera/Projects/backend
PYTHONPATH=/home/santera/Projects/backend ./.venv/bin/python scripts/run_rag_evaluation.py \
  --scenarios \
    metric_intent \
    negative_metric_intent \
    general_po_summary \
    source_diversity_stress \
    technical_root_cause \
    release_notes_focus \
    no_answer_groundedness \
    incident_summary \
    follow_up_continuation \
    topic_switch \
    follow_up_action_plan \
    explicit_topic_switch \
    follow_up_metric_intent \
    follow_up_negative_metric \
    follow_up_incident \
    bucket_alpha_positive \
    bucket_beta_positive \
    bucket_no_leak_negative \
  --models gemma4:12b qwen3.5:9b qwen3:14b \
  --name full_project_core_chat_three_models \
  --notes full-project-core-chat-context-access \
  --timeout-seconds 240
```

## Stage B: Summarization / Long Memory, 9B Only

Model:

- `qwen3.5:9b`

Scenarios:

```text
summary_long_follow_up
summary_topic_switch
summary_metric_follow_up
summary_negative_metric_follow_up
llm_summary_structured
prompt_memory_budget
memory_permissions_long_follow_up
memory_csv_import_long_follow_up
memory_explicit_topic_switch_csv
memory_return_to_previous_topic
memory_metric_permissions_follow_up
memory_negative_metric_permissions_follow_up
memory_incident_follow_up
memory_release_notes_follow_up
memory_short_follow_up_recent_only
```

Command:

```bash
cd /home/santera/Projects/backend
PYTHONPATH=/home/santera/Projects/backend ./.venv/bin/python scripts/run_rag_evaluation.py \
  --scenarios \
    summary_long_follow_up \
    summary_topic_switch \
    summary_metric_follow_up \
    summary_negative_metric_follow_up \
    llm_summary_structured \
    prompt_memory_budget \
    memory_permissions_long_follow_up \
    memory_csv_import_long_follow_up \
    memory_explicit_topic_switch_csv \
    memory_return_to_previous_topic \
    memory_metric_permissions_follow_up \
    memory_negative_metric_permissions_follow_up \
    memory_incident_follow_up \
    memory_release_notes_follow_up \
    memory_short_follow_up_recent_only \
  --models qwen3.5:9b \
  --name full_project_summary_memory_qwen35_9b \
  --notes full-project-summary-memory-selected-model \
  --timeout-seconds 240
```

## Stage C: Documents, Best Document Model Only

Model:

- replace `<BEST_DOCUMENT_MODEL>` with the winner from the document-only regression.

Scenarios:

```text
pdf_text_ingestion
excel_ingestion
docx_ingestion
image_ocr_ingestion
image_digest_ingestion
docx_embedded_image_digest
docx_text_image_mismatch
office_media_consistency_mismatch
excel_embedded_image_digest
excel_chart_pareto_ingestion
excel_native_chart_ingestion
legacy_xls_text_ingestion
legacy_xls_embedded_image_digest
docx_table_image_anchor_digest
xlsx_row_image_anchor_digest
scanned_table_image_anchor_digest
```

Command:

```bash
cd /home/santera/Projects/backend
PYTHONPATH=/home/santera/Projects/backend ./.venv/bin/python scripts/run_rag_evaluation.py \
  --scenarios \
    pdf_text_ingestion \
    excel_ingestion \
    docx_ingestion \
    image_ocr_ingestion \
    image_digest_ingestion \
    docx_embedded_image_digest \
    docx_text_image_mismatch \
    office_media_consistency_mismatch \
    excel_embedded_image_digest \
    excel_chart_pareto_ingestion \
    excel_native_chart_ingestion \
    legacy_xls_text_ingestion \
    legacy_xls_embedded_image_digest \
    docx_table_image_anchor_digest \
    xlsx_row_image_anchor_digest \
    scanned_table_image_anchor_digest \
  --models <BEST_DOCUMENT_MODEL> \
  --name full_project_documents_best_model \
  --notes full-project-document-slice-selected-model \
  --timeout-seconds 240
```

## Expected Result Shape

This full regression produces:

- Stage A: `18 scenarios x 3 models = 54 results`
- Stage B: `15 scenarios x 1 model = 15 results`
- Stage C: `16 scenarios x 1 model = 16 results`

Total: `85 results`

This is much smaller and more diagnostic than `49 scenarios x 3 models = 147 results`, while still covering the whole project.

## What This Does Not Cover Yet

The future long user journey is intentionally not included here. That should be a separate end-to-end scenario with one long session, cross-topic document questions, summarization, topic switching, and return-to-context behavior.
