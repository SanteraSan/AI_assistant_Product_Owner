# Enterprise Product Expansion Plan

## Context

После M5 document ingestion, backend hardening и M7 LoRA Text-to-SQL проект получил сильное backend/RAG/ML ядро.

Следующий фокус: приблизить проект к product/enterprise версии через UI, auth/RBAC, model gateway, external providers, workflow automation, agents/tool-use и event-driven ingestion.

Цель этого плана — не заменить текущую архитектуру, а нарастить поверх неё production-minded слои.

## Target Architecture

```text
Browser UI
  -> BFF / Session Layer
    -> Backend API
      -> Auth/RBAC Context
      -> Buckets/Documents/Chat/RAG/Text-to-SQL
      -> Tool Registry
      -> Ingestion Jobs
    -> Model Gateway
      -> Ollama Provider
      -> OpenAI-Compatible External Providers
Keycloak
PostgreSQL
Qdrant
Redis
Kafka
Object Storage
n8n / Email / External Workflows
```

## Principles

- Backend access filters remain authoritative. LLMs, agents and external gateways must never decide what the user can access.
- UI should be simple but real: login, buckets, upload, ingestion status, chat and source evidence.
- Provider abstraction should hide local/external model differences from business logic.
- Frameworks such as LangGraph, LangChain or LlamaIndex should be adapter/orchestration layers, not a rewrite of current services.
- Kafka and workflow tooling should be introduced around explicit events, not as hidden background magic.
- Every enterprise layer should add traceability: request id, user id, tenant id, bucket id, document id, tool call id and model provider.
- Frontend follows Flux-style state flow: actions update Zustand/client state or React Query/server state first, then widgets render from state. Pages should not own business state through scattered local `useState`.

## Stage E0: UI Skeleton

Goal:

- create the first usable web interface over existing backend capabilities.

Scope:

- simple login mock without Keycloak;
- bucket list and bucket creation;
- document upload;
- ingestion status display;
- chat panel with bucket selection;
- source/evidence panel for RAG answers;
- model selector prepared for local/external providers;
- minimal layout that can later receive real auth.

Recommended implementation:

- frontend: React/Vite or Next.js;
- keep UI contracts explicit and typed;
- use Zustand for client/business state and React Query for server state;
- keep backend endpoints thin;
- do not move ingestion/RAG logic into frontend;
- start with mock auth context: `user_id`, `tenant_id`, roles.

Definition of done:

- user can open UI, select/create bucket, upload document, ask a chat question and see answer sources;
- all requests carry a mock user/tenant context;
- UI state is visible enough to demo the product flow;
- no Keycloak dependency yet.

### Stage E0.1: Document Library And Access Model

Goal:

- split "document exists in the system" from "document is linked to a bucket";
- introduce owner/visibility/role access rules before full Keycloak/RBAC integration.

Scope:

- `document_assets` as system-level document library;
- `bucket_documents` as many-to-many links between buckets and documents;
- `document_acl_entries` for explicit grants;
- default uploaded document visibility is owner-only/private;
- admins can see tenant documents;
- role-based visibility supports team-lead/admin/developer style access;
- bucket membership never grants access by itself.

Access rule:

```text
can_read(document, user) =
  same tenant
  AND (
    user is owner
    OR user has admin role
    OR visibility is tenant
    OR visibility is role and user roles intersect allowed roles
    OR explicit ACL grants read/admin
  )
```

Definition of done:

- user can see own documents;
- user can see available documents according to access policy;
- user can add an accessible existing document to a bucket;
- user can upload a private document and link it to a bucket;
- RAG-facing bucket document lists never include inaccessible documents.

### Stage E0.2: Staged Upload And Indexing Baseline

Goal:

- make document upload production-like instead of "file selected means permanently saved";
- keep bucket edits explicit through draft/stage/commit;
- index committed documents into Qdrant so RAG can answer from uploaded files.

Flow:

```text
UI file selection
-> staged_document_uploads
-> user reviews draft files in bucket modal
-> commit bucket changes
-> document_assets + bucket_documents
-> document_indexing_jobs
-> in-process indexing baseline
-> Qdrant chunks with tenant/bucket/document metadata
```

Baseline constraints:

- Kafka is not introduced in E0.2;
- `document_indexing_jobs` is the architectural boundary that can later publish/consume Kafka events;
- committed files live under document-level storage, not bucket folders, because one document can belong to many buckets;
- removing a document from a bucket removes only `bucket_documents`, not `document_assets`.

Definition of done:

- staged uploads can be created and cancelled;
- bucket modal has explicit save/commit behavior;
- committed documents get `indexing` then `indexed` or `index_failed` status;
- uploaded document chunks are upserted to Qdrant with `tenant_id`, `bucket_id`, `document_id`, `source_path`, and traceable `document_metadata`;
- UI clearly distinguishes staged, indexing, indexed, and failed documents.

### Stage E0.3: Chat RAG Integration Baseline

Goal:

- replace mock assistant responses in the web UI with real `/rag/chat` calls;
- make model, tenant, bucket and uploaded-document context explicit before Keycloak/RBAC.

Scope:

- typed frontend API client for `/rag/chat`;
- chat store actions for user messages, assistant messages, session id and context metadata;
- PostgreSQL-backed chat sessions/messages scoped by mock tenant/user headers;
- loading/error states in the chat composer and message stream;
- real RAG sources in the source/evidence panel;
- context rule for the current backend filter model: use `bucket_ids` when chatting with a selected bucket, use explicit `document_ids` when indexed chat attachments are present.

Definition of done:

- sending a chat message calls `/rag/chat`;
- response text and sources come from backend, not mock data;
- selected model and mock tenant/user context are passed to backend;
- indexed chat attachments can be used as explicit document context;
- chat history survives frontend reload through `/chat/sessions` and `/chat/sessions/{session_id}/messages`;
- frontend build/lint and backend tests pass.

## Stage E1: Keycloak, BFF And RBAC

Goal:

- replace mock auth with real OIDC/OAuth2 and role-based access control.

Scope:

- Keycloak realm, clients, roles and test users;
- BFF session layer using secure httpOnly cookies;
- backend JWT validation or trusted BFF headers, depending on deployment mode;
- `UserContext` and `TenantContext` in backend;
- roles such as `admin`, `analyst`, `viewer`, `ingestion_manager`, `model_manager`;
- tenant/bucket/document access enforcement before RAG prompt construction.

Definition of done:

- users log in through Keycloak;
- backend receives authenticated identity and roles;
- bucket/document/chat access is filtered before retrieval;
- unauthorized users cannot see other tenant/bucket data.

## Stage E2: Model Gateway And External Providers

Goal:

- support local Ollama and OpenAI-compatible external models behind one provider interface.

Scope:

- `LLMProvider` abstraction;
- `OllamaProvider`;
- `OpenAICompatibleProvider`;
- model registry with capabilities: chat, embeddings, vision, JSON mode, tool calling;
- provider fallback policy;
- per-tenant model allowlist;
- cost/latency/audit metadata.

Fine-tuning notes:

- local LoRA/QLoRA remains the right path for open-weight models;
- closed external models generally cannot use LoRA because weights are unavailable;
- external fine-tuning is provider-specific and should be handled through a separate provider adapter.

Definition of done:

- user or backend policy can choose local/external model;
- local model outage can fall back to an external provider when policy allows it;
- all model calls are logged with provider/model/request id.

## Stage E3: Agents, Function Calling And Tool Use

Goal:

- expose existing backend capabilities as controlled tools.

Candidate tools:

- `rag_search`;
- `text_to_sql`;
- `execute_readonly_sql`;
- `ingest_document`;
- `list_buckets`;
- `get_document_status`;
- `generate_report`;
- `send_email_summary`.

Rules:

- tools enforce RBAC and tenant filters internally;
- tool inputs use Pydantic schemas;
- tool calls are audited;
- agent output remains grounded in retrieved/tool-produced evidence.

Definition of done:

- chat flow can call at least RAG and Text-to-SQL tools;
- tool call trace is visible in logs or UI;
- unauthorized tool calls fail before execution.

## Stage E4: n8n And Email/Workflow Integration

Goal:

- ingest external business content through workflow automation.

Scope:

- n8n workflows for email/webhook/document ingestion;
- Gmail integration through OAuth2/Gmail API;
- Yandex/corporate mail through IMAP/API where practical;
- Outlook/Microsoft 365 through Microsoft Graph;
- optional Outlook add-in as future UI extension.

Definition of done:

- n8n can receive or fetch a document and call backend ingestion endpoint;
- uploaded content lands in a tenant/bucket with traceable metadata;
- ingestion status and errors are visible.

## Stage E5: Kafka And Event-Driven Ingestion

Goal:

- support high-volume document and evaluation workloads with durable event streams.

Candidate events:

- `document.uploaded`;
- `document.parsed`;
- `document.chunked`;
- `document.embedded`;
- `document.indexed`;
- `evaluation.requested`;
- `evaluation.completed`;
- `report.generated`.

Consumers:

- ingestion worker;
- OCR/vision worker;
- embedding worker;
- evaluation worker;
- notification worker.

Definition of done:

- document ingestion can run asynchronously through events;
- processing state remains persisted in PostgreSQL;
- failed events can be retried or inspected;
- Kafka is used for durable workflow events, while Redis remains useful for rate limits and lightweight coordination.

## Stage E6: Framework Adapters

Goal:

- selectively use LangGraph/LangChain/LlamaIndex/CrewAI where they add value.

Recommended approach:

- LangGraph for explicit agent workflows and tool routing;
- LlamaIndex for connectors or retrieval experiments;
- LangChain for provider/tool abstractions when useful;
- CrewAI only for bounded multi-agent demos, not core backend ownership.

Definition of done:

- framework integration calls current backend services instead of replacing them;
- evaluation scenarios confirm the framework layer does not bypass access controls.

## Stage E7: Product Hardening

Goal:

- make the app demoable as a product rather than a collection of backend scripts.

Scope:

- deployment profiles;
- object storage for uploaded files;
- stronger admin/tenant management;
- observability dashboards;
- audit export;
- user-facing report generation;
- regression suite covering UI, auth, RAG, Text-to-SQL and ingestion.

## Recommended Order

1. E0 UI Skeleton.
2. E1 Keycloak/BFF/RBAC.
3. E2 Model Gateway and external providers.
4. E3 Tool-use/agents.
5. E4 n8n/email workflows.
6. E5 Kafka event backbone.
7. E6 framework adapters.
8. E7 product hardening.

This order gives a visible product surface first, then gradually replaces mocks with enterprise-grade infrastructure.
