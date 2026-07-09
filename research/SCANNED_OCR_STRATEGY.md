# Scanned OCR Strategy

## Context

M5.8.2 and M5.8.3 covered two different levels of scanned table processing:

- `M5.8.2` is the stable baseline inside the backend. It uses a lightweight PIL-based grid detector, Tesseract OCR for row context, and the existing image OCR/digest pipeline for image cells.
- `M5.8.3` is the advanced research spike. It runs PaddleOCR `PPStructureV3` in a separate Python 3.11 environment and checks whether a heavier layout OCR stack gives better table/image evidence.

The goal is not to replace the backend baseline immediately. The goal is to understand the tradeoff before adding a heavy dependency to ingestion.

## Current Decision

Keep the M5 production path on the lightweight baseline for now.

The baseline is enough for the current project stage because it is predictable, testable, has no heavy ML runtime dependency, and already creates useful `linked_text` evidence for images inside clearly ruled scanned tables.

Keep PaddleOCR as an optional advanced path and future hardening candidate.

PaddleOCR `PPStructureV3` is useful because it detected the table block, layout boxes, OCR text, and image references on `data/raw/scanned_fixtures/scanned-table-products.png`. Its output is richer than the baseline, but it is also heavier and needs careful normalization before it can safely feed RAG evidence.

## Baseline Strengths

- Small dependency footprint and easier local setup.
- Deterministic behavior on good scans with visible table grid lines.
- Direct mapping from detected row/cell crops to backend metadata such as `anchor_type=scanned_table_cell`, `table_row_bbox`, `image_cell_bbox`, and `linked_text`.
- Good fit for M5 regression because it avoids adding another fragile runtime layer before the large evaluation pass.

## Baseline Limits

- Requires visible table lines.
- Assumes a relatively simple table layout.
- OCR quality depends on Tesseract and image quality.
- Does not understand complex layout semantics beyond the detected grid.

## PaddleOCR Strengths

- Detects higher-level document layout, not only grid lines.
- Produces a structured table representation as HTML.
- Finds image references inside table cells.
- Has a path toward harder documents: tables without clear grid lines, mixed document layouts, and scanned PDFs after page rendering.

## PaddleOCR Risks

- Heavy optional dependency stack.
- Needs a separate compatible environment in this project: Python 3.11, `paddleocr==3.7.0`, `paddlex[ocr]==3.7.2`, and `paddlepaddle==3.2.2`.
- `paddlepaddle==3.3.1` hit a CPU oneDNN/PIR runtime error during the spike.
- Raw output is not ingestion-ready yet. HTML table cells and image refs must be normalized into stable `RawDocument` content and metadata.

## Integration Rule

Do not pass raw PaddleOCR output directly to the LLM.

If PaddleOCR is integrated later, add a normalization layer first:

- parse the table HTML into rows and cells;
- link each image reference to the nearest row/cell text;
- convert each linked visual item into the same evidence shape used by the baseline;
- preserve source metadata such as OCR engine, model versions, bounding boxes, row/cell coordinates, and confidence where available;
- keep PaddleOCR optional, configurable, and isolated from the default ingestion path.

## Next Step

Run the large M5 regression with the current baseline first.

Only integrate PaddleOCR after the regression shows a real failure class that the baseline cannot handle, for example tables without visible lines, mixed page layouts, or scanned PDFs where grid detection is insufficient.
