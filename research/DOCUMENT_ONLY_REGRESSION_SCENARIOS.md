# Document-Only Regression Scenarios

Goal: choose the best local model for document-heavy RAG before running the broader project regression.

This is a document-only model selection run. It covers PDF, Excel, DOCX, image OCR, image vision digest, embedded office images, charts, legacy XLS, XLSX/DOCX image anchors, scanned tables, and office media consistency evidence.

Current evaluator has `16` document-specific scenarios. Running them on `3` models produces `48` document results.

## Models

- `gemma4:12b`
- `qwen3.5:9b`
- `qwen3:14b`

## Scenario IDs

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

## Command

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
  --models gemma4:12b qwen3.5:9b qwen3:14b \
  --name m5_document_only_three_models \
  --notes document-model-selection-after-m5-regression-fixes \
  --timeout-seconds 240
```

## How To Pick The Best Document Model

Primary criteria:

- zero technical errors;
- highest full-pass count by quality flags;
- strongest behavior on visual/document edge cases:
  - `docx_text_image_mismatch`
  - `office_media_consistency_mismatch`
  - `xlsx_row_image_anchor_digest`
  - `scanned_table_image_anchor_digest`
  - `legacy_xls_embedded_image_digest`

Secondary criteria:

- lower average latency;
- clearer Russian answers;
- fewer overly cautious “cannot answer” responses when evidence is present;
- better source use discipline.

## Expected Decision Output

After the run, record:

- chosen document model;
- pass/fail count per model;
- latency summary per model;
- any remaining weak scenarios;
- whether the chosen model is stable enough for the full project regression document slice.
