# Text-to-SQL Dataset V2

## Goal

V2 makes the Text-to-SQL benchmark more honest than V1.

V1 proved that LoRA can learn the local SQL style, but its split was example-level. V2 uses an intent-level split: train, validation, and test contain different intent families.

## Location

- `data/text_to_sql/v2/train.jsonl`
- `data/text_to_sql/v2/validation.jsonl`
- `data/text_to_sql/v2/test.jsonl`
- `data/text_to_sql/v2/manifest.json`

## Shape

- total examples: `165`
- total intents: `33`
- train examples: `105`
- validation examples: `30`
- test examples: `30`
- train intents: `21`
- validation intents: `6`
- test intents: `6`
- split policy: `intent_level_split`

Each intent has 5 Russian instruction variants.

## Evaluation Metadata

Each example includes:

- `intent_id`;
- `required_tables`;
- `required_terms`;
- `tags`;
- `split`.

`required_terms` lets evaluation check semantic SQL shape, not just exact-match:

- aggregations: `count`, `avg`, `group by`;
- sorting and limits: `order by`, `limit`;
- filters: `where`, `is null`, `is not null`;
- JSONB/LATERAL patterns: `cross join lateral`, `jsonb_array_elements_text`;
- date patterns: `date_trunc`.

## Covered Areas

- evaluation run analytics;
- evaluation result errors and quality flags;
- chat message analytics;
- conversation summary analytics;
- RAG request analytics;
- RAG source analytics;
- JSONB expansion;
- joins;
- null filters;
- date grouping;
- ratio/error-rate style analytics.

## Why This Matters

The V2 test split checks unseen intent families. This makes it harder for LoRA to pass by simply memorizing examples.

The expected quality target is therefore different:

- `valid_sql` should stay near `100%`;
- `required_tables_present` should stay near `100%`;
- `required_terms_present` should improve over the base model;
- `normalized_exact_match` is useful but should be interpreted carefully because semantically valid SQL may differ from the reference query.
