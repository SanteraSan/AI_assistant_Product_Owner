# M5 Full Regression 2026-07-09

## Run

- Run id: `1ffb88f8-6550-45d1-8723-77cea60dcd33`
- Name: `m5_full_regression_three_models`
- Models: `gemma4:12b`, `qwen3.5:9b`, `qwen3:14b`
- Scenarios: `49`
- Total results: `147`
- Status: `completed`
- Technical errors: `0`
- Average latency: `8602 ms`
- P50 latency: `8711 ms`
- Max latency: `18825 ms`

## Result Summary

- `gemma4:12b`: `47/49` full pass, `2` quality-flag failures.
- `qwen3.5:9b`: `45/49` full pass, `4` quality-flag failures.
- `qwen3:14b`: `47/49` full pass, `2` quality-flag failures.

Overall: `139/147` full pass by current evaluator flags.

## Failed Quality Flags

- `excel_ingestion`: failed on all three models.
  - Sources and Excel metadata were present.
  - Responses refused to answer because the retrieved Excel context did not contain `enterprise onboarding blockers`.
  - Likely action: review this scenario after M5 fixture expansion. It may be an outdated evaluator prompt or marker expectation rather than a parser failure.

- `xlsx_row_image_anchor_digest`: failed on all three models.
  - `image_digest` sources from `hard_for_analis_2.xlsx` were retrieved.
  - Models did not find a product matching `4,1 % алкоголь`, `11% плотность`, and `3500 р`.
  - Flags `xlsx_linked_text_ok` and `xlsx_anchor_row_metadata_ok` failed.
  - Likely action: inspect XLSX image anchor metadata and retrieval supplement. This is the main real M5.8.1/M5.8.2 follow-up.

- `docx_text_image_mismatch`: failed only on `qwen3.5:9b`.
  - Text and visual evidence sources were present.
  - The answer still stated that the text and image do not match.
  - Likely action: evaluator marker group is probably too strict for this wording.

- `office_media_consistency_mismatch`: failed only on `qwen3.5:9b`.
  - `office_media_consistency` source and metadata were present.
  - The model was more cautious and did not clearly affirm the precomputed mismatch.
  - Likely action: review prompt wording and marker groups for the consistency scenario.

## Decision

Do not move to `M5.9 Voice UI Bridge` yet.

First, debug the two broad failures:

- `xlsx_row_image_anchor_digest` because it indicates a real retrieval/anchor quality issue.
- `excel_ingestion` because all models fail it and the scenario may be stale after the fixture set changed.

The two `qwen3.5:9b`-only failures can be handled after that as evaluator/prompt hardening unless deeper inspection shows missing evidence.

## Follow-Up Fix 2026-07-09

Run id: `9dafb2f1-dd15-4c0c-ae98-bef31758c202`

Targeted regression:

- Scenarios: `excel_ingestion`, `docx_text_image_mismatch`, `office_media_consistency_mismatch`, `xlsx_row_image_anchor_digest`
- Models: `gemma4:12b`, `qwen3.5:9b`, `qwen3:14b`
- Total results: `12`
- Technical errors: `0`
- Quality-flag failures: `0`

Fixes:

- `xlsx_row_image_anchor_digest`: added lexical supplement for XLSX anchored `image_digest` sources so exact row evidence such as `4,1`, `11%`, and `3500` can lift the correct embedded images above pure vector similarity. Verified that `anchored_image5` and `anchored_image7` from row `11` are retrieved first.
- `excel_ingestion`: scoped the scenario to `product_owner_metrics.xlsx`, which is the actual fixture containing `enterprise onboarding`, `Excel import validation`, and the recommendation.
- `excel_ingestion`: changed the strict `validation` marker to a marker group that also accepts Russian wording such as `валидац` and `провер`.
- `office_media_consistency_mismatch`: compacted ingestion-time consistency evidence so `Consistency status` and `Consistency reason` stay in the first and only chunk. This prevents retrieval from selecting a middle chunk without the precomputed mismatch summary.

Result:

- The four known failures from the full regression are fixed in targeted regression.
- Before moving to `M5.9`, a final full M5 run can be repeated to confirm there are no secondary regressions.
