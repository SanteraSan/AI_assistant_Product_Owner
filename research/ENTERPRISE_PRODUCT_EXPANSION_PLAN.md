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
