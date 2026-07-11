# AI Development Rules For Product Owner Assistant

These rules are for AI coding agents working on this pet project. The project is a learning and portfolio-grade Smart AI Assistant for a Product Owner, focused on local LLMs, RAG, Qdrant, PostgreSQL, Ollama, document ingestion, evaluation, and production-minded engineering practices.

## Language And Communication

- Communicate with the user in Russian by default.
- Keep explanations educational: explain not only what changed, but why the engineering choice is reasonable.
- Use English for code identifiers when it matches the existing codebase.
- Be honest about uncertainty, trade-offs, limitations, and future hardening.
- Do not hide shortcuts. If something is a pragmatic baseline, say so and document the stronger future version.

## Working Style

- Work incrementally in small, reviewable steps.
- Before editing, inspect the existing code and follow local patterns.
- Prefer improving the current architecture over rewriting large parts.
- Do not introduce heavy infrastructure just because it is common in production. Add future hardening notes when the idea is valid but too large for the current step.
- Treat every stage as a lab experiment: implement, test, evaluate, document observations, and adjust the plan.
- When the user proposes a new idea, analyze whether it belongs in the current milestone, a small sub-step, or future hardening.

## Architecture Principles

- Keep FastAPI entrypoints thin. Do not let `main.py` become a business-logic container.
- Put orchestration and domain behavior into dedicated services under `backend/app/services/`.
- Keep infrastructure clients under `backend/app/clients/`.
- Keep config in `backend/app/core/config.py`; avoid scattering magic constants through the code.
- Prefer explicit, traceable data flow over hidden framework magic.
- Add abstractions only when they reduce real duplication or clarify ownership boundaries.
- Preserve existing user changes. Do not revert unrelated files.

## Frontend Architecture Principles

- Use FSD boundaries for frontend code: `app`, `pages`, `widgets`, `features`, `entities`, `shared`.
- Keep reusable UI components prop-driven and free of business decisions.
- Follow Flux-style data flow: user interaction calls an action, action updates store/server state, components render from the resulting state.
- Use Zustand for client/business state such as active chat, selected bucket, selected model, selected mode, mock/current user and UI modal flags.
- Use React Query for server state such as buckets, documents, upload mutations and future RAG requests.
- Avoid scattering business `useState` across pages. Page components should orchestrate stores, queries and widgets, not own domain behavior.
- Do not call `fetch` directly from UI components. Keep typed API calls in `entities/*/api.ts` or `shared/api`.

## RAG And Evidence Boundaries

- Evidence must come from retrieved sources, not from memory or assumptions.
- Conversation memory and summaries are context, not evidence.
- Backend filters must enforce access before prompt construction. The LLM must never decide what the user is allowed to see.
- `tenant_id`, `bucket_id`, `document_id`, `source_type`, `source_path`, and `document_metadata` are important retrieval and audit boundaries.
- When adding new retrieval behavior, keep it inside the already allowed tenant/bucket/document/source path scope.
- If answer quality fails, diagnose the layer first: ingestion, metadata, chunking, retrieval, reranking, prompt, evaluator, or model behavior.

## Document Ingestion Principles

- Every document representation should preserve traceability:
  - `tenant_id`
  - `bucket_id`
  - `document_id`
  - `source_type`
  - `source_path`
  - meaningful `document_metadata`
- Multiple representations of one file are valid and encouraged:
  - plain text evidence
  - page evidence
  - row evidence
  - table evidence
  - OCR evidence
  - vision digest evidence
  - chart evidence
  - consistency evidence
- Do not force all file types into one generic text blob when a structured representation is available.
- For Office files, distinguish actual embedded images from native charts. They are different evidence types.
- For multimodal data, prefer converting visual content into searchable text evidence before RAG answer generation.

## Evaluation And Testing

- Every meaningful feature should have focused unit tests.
- Every user-visible RAG behavior should have an evaluation scenario when practical.
- Keep evaluation scenarios concrete. It is acceptable for a regression prompt to reference a known fixture.
- Keep product prompts universal; do not copy fixture-specific evaluation prompts into product behavior.
- Strengthen evaluators instead of weakening them blindly:
  - use marker groups for wording variants;
  - use numeric normalization for amounts;
  - verify source metadata;
  - verify no-leak boundaries;
  - verify required evidence layers appear in sources.
- If an evaluation fails, inspect whether the answer is actually wrong or the marker is too brittle.
- Store important model comparison artifacts in `research/*.jsonl`.

## Documentation Discipline

- After each completed milestone or sub-step, update:
  - `backend/README.md`
  - `research/LESSONS_LEARNED.md`
  - `research/RAG_EVALUATION_CHECKLIST.md`
  - relevant plan files under `.cursor/plans/`
- The journal should capture:
  - context;
  - what changed;
  - checks and run IDs;
  - observations;
  - conclusions;
  - future hardening.
- Documentation should explain architectural decisions, not just list changed files.
- Keep documentation in Russian unless a code/API term is naturally English.

## Git And File Safety

- Commit only when the user explicitly asks.
- Before committing, inspect status, diff, and recent commit style.
- Do not commit personal/local raw files unless the user explicitly approves them.
- Avoid committing private PDFs, resumes, or ad-hoc local documents.
- Do not revert user changes unless explicitly requested.
- Do not run destructive git commands unless explicitly requested and understood.

## M5 Development Guidance

- M5 is a production-minded ingestion/retrieval layer, not a demo file uploader.
- Continue to treat buckets and tenant metadata as architectural boundaries.
- For new file types or hard cases:
  - add a small fixture;
  - inspect what the parser can really extract;
  - create traceable `RawDocument` evidence;
  - add focused unit tests;
  - add evaluation scenarios;
  - run at least `qwen3.5:9b` smoke;
  - use three-model smoke when comparing model behavior matters.
- Prefer adding new evidence layers over overloading an existing source type.
- Keep legacy `.xls`, old `.doc`, SVG rendering, and complex chart rendering as explicit hardening items unless the current step is about them.

## M6 And Voice/UI Guidance

- Before M6, finish a strong M5 baseline and run a broad M5 regression.
- Treat voice UI as a bridge step, not as a reason to weaken backend boundaries.
- Audio transcription should produce text that enters the existing chat/RAG pipeline.
- Do not let UI concerns leak into ingestion/retrieval services.
- Keep API boundaries clear so frontend, transcription, and RAG can evolve separately.

## Model Selection Guidance

- Do not assume the biggest model is the best for every task.
- Compare models on the actual scenario type:
  - summary/context memory;
  - document QA;
  - OCR/vision-derived evidence;
  - structured output;
  - grounded no-answer behavior.
- Track latency and quality separately.
- Prefer `qwen3.5:9b` for fast recurring regressions when quality is sufficient.
- Keep `gemma4:12b` and `qwen3:14b` as comparison candidates for harder reasoning or vision-adjacent stages.

## Future Hardening Pattern

When a production concern is real but too large for the current step, document it as future hardening. Examples:

- Alembic migrations;
- auth/RBAC and policy engines;
- MinIO/S3 storage;
- Redis/queues/Kafka for ingestion workers;
- incremental indexing for large corpora;
- OpenRouter/local-first provider fallback;
- LLM-based consistency checkers;
- layout-aware document parsing;
- legacy Office conversion.

Do not implement all of these prematurely. Preserve the project rhythm: small baseline, evaluation, hardening, documentation.
