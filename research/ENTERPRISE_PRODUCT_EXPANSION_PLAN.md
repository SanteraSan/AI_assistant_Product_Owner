# Enterprise Product Expansion Plan

## Контекст

После M5 document ingestion, backend hardening и M7 LoRA Text-to-SQL проект получил сильное backend/RAG/ML ядро.

Следующий фокус: приблизить проект к product/enterprise версии через UI, auth/RBAC, model gateway, external providers, workflow automation, agents/tool-use и event-driven ingestion.

Цель этого плана — не заменить текущую архитектуру, а нарастить поверх неё production-minded слои.

## Целевая архитектура

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

## Принципы

- Backend access filters остаются авторитетными. LLM, agents и external gateways никогда не должны решать, к чему пользователь имеет доступ.
- UI должен быть простым, но настоящим: login, buckets, upload, статус ingestion, chat и source evidence.
- Provider abstraction должна скрывать различия local/external моделей от бизнес-логики.
- Frameworks вроде LangGraph, LangChain или LlamaIndex должны быть adapter/orchestration слоями, а не переписыванием текущих сервисов.
- Kafka и workflow tooling нужно вводить вокруг явных events, а не как скрытую background-магию.
- Каждый enterprise-слой должен добавлять traceability: request id, user id, tenant id, bucket id, document id, tool call id и model provider.
- Frontend следует Flux-style data flow: actions сначала обновляют Zustand/client state или React Query/server state, затем widgets рендерятся из state. Pages не должны владеть business state через разрозненный локальный `useState`.

## Этап E0: UI Skeleton

Цель:

- создать первый usable web interface поверх уже существующих backend-возможностей.

Scope:

- простой login mock без Keycloak;
- список buckets и создание bucket;
- document upload;
- отображение статуса ingestion;
- chat panel с выбором bucket;
- source/evidence panel для RAG-ответов;
- model selector, подготовленный под local/external providers;
- минимальный layout, который позже сможет принять настоящий auth.

Рекомендуемая реализация:

- frontend: React/Vite или Next.js;
- держать UI contracts явными и typed;
- использовать Zustand для client/business state и React Query для server state;
- держать backend endpoints тонкими;
- не переносить ingestion/RAG logic во frontend;
- стартовать с mock auth context: `user_id`, `tenant_id`, roles.

Definition of done:

- пользователь может открыть UI, выбрать/создать bucket, загрузить document, задать вопрос в chat и увидеть sources ответа;
- все запросы несут mock user/tenant context;
- UI state достаточно видимый, чтобы показать product flow;
- зависимости от Keycloak ещё нет.

### Этап E0.1: Document Library And Access Model

Цель:

- разделить «document существует в системе» и «document привязан к bucket»;
- ввести owner/visibility/role access rules до полной интеграции Keycloak/RBAC.

Scope:

- `document_assets` как system-level document library;
- `bucket_documents` как many-to-many связи между buckets и documents;
- `document_acl_entries` для explicit grants;
- default visibility загруженного document — owner-only/private;
- admins видят documents tenant;
- role-based visibility поддерживает доступ в стиле team-lead/admin/developer;
- membership в bucket сам по себе доступ не даёт.

Правило доступа:

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

- пользователь видит свои documents;
- пользователь видит available documents согласно access policy;
- пользователь может добавить доступный существующий document в bucket;
- пользователь может загрузить private document и привязать его к bucket;
- RAG-facing списки documents bucket никогда не включают недоступные documents.

### Этап E0.2: Staged Upload And Indexing Baseline

Цель:

- сделать document upload production-like, а не «файл выбран = файл навсегда сохранён»;
- держать правки bucket явными через draft/stage/commit;
- индексировать committed documents в Qdrant, чтобы RAG мог отвечать по загруженным файлам.

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

Ограничения baseline:

- Kafka на E0.2 не вводится;
- `document_indexing_jobs` — архитектурная граница, которая позже сможет publish/consume Kafka events;
- committed files живут в document-level storage, а не в папках bucket, потому что один document может принадлежать многим buckets;
- удаление document из bucket удаляет только `bucket_documents`, не `document_assets`.

Definition of done:

- staged uploads можно создавать и отменять;
- bucket modal имеет явное поведение save/commit;
- committed documents получают статусы `indexing`, затем `indexed` или `index_failed`;
- chunks загруженных documents upsert-ятся в Qdrant с `tenant_id`, `bucket_id`, `document_id`, `source_path` и трассируемым `document_metadata`;
- UI ясно различает staged, indexing, indexed и failed documents.

### Этап E0.3: Chat RAG Integration Baseline

Статус: **done** (2026-07-14). Следующий фокус — E1 Keycloak/BFF/RBAC.

Цель:

- заменить mock-ответы ассистента в web UI на реальные вызовы `/rag/chat`;
- сделать model, tenant, bucket и uploaded-document context явными до Keycloak/RBAC.

Scope:

- typed frontend API client для `/rag/chat`;
- chat store actions для user messages, assistant messages, session id и context metadata;
- chat sessions/messages в PostgreSQL, scoped по mock tenant/user headers;
- loading/error states в chat composer и message stream;
- реальные RAG sources в source/evidence panel;
- правило context для текущей backend filter model: использовать `bucket_ids` при чате с выбранным bucket, использовать явные `document_ids`, когда есть indexed chat attachments.

Definition of done:

- отправка chat message вызывает `/rag/chat`;
- текст ответа и sources приходят из backend, а не из mock data;
- выбранная model и mock tenant/user context передаются в backend;
- indexed chat attachments можно использовать как явный document context;
- chat history переживает reload frontend через `/chat/sessions` и `/chat/sessions/{session_id}/messages`;
- frontend build/lint и backend tests проходят.

## Этап E1: Keycloak, BFF And RBAC

Статус: **done** (2026-07-14). Browser smoke: admin/analyst/viewer login, logout/SSO switch, document RBAC (private/tenant/role) подтверждены.

Цель:

- заменить mock auth на настоящий OIDC/OAuth2 и role-based access control.

Scope:

- Keycloak realm, clients, roles и test users;
- BFF session layer на secure httpOnly cookies;
- backend JWT validation или trusted BFF headers в зависимости от deployment mode;
- `UserContext` и `TenantContext` в backend;
- roles вроде `admin`, `analyst`, `viewer`, `ingestion_manager`, `model_manager`;
- enforcement доступа tenant/bucket/document до построения RAG prompt.

Definition of done:

- пользователи входят через Keycloak;
- backend получает authenticated identity и roles;
- доступ к bucket/document/chat фильтруется до retrieval;
- unauthorized пользователи не видят данные чужого tenant/bucket.

## Этап E2: Model Gateway And External Providers

Статус: **blocked** (2026-07-14) — kickoff decisions сохранены; реализация отложена из‑за VPN / недоступности внешнего Gemini API. Не реализуем пустой gateway «на вырост». Вернуться к E2.1 после сетевого доступа к Google AI Studio.

Цель:

- поддержать local Ollama и OpenAI-compatible external models за одним provider interface.

### Решения kickoff (2026-07-14)

Baseline external provider:

- **Google AI Studio / Gemini** через OpenAI-compatible endpoint  
  (`https://generativelanguage.googleapis.com/v1beta/openai/`);
- env: `GEMINI_API_KEY` (бесплатный ключ из [Google AI Studio](https://aistudio.google.com/apikey));
- внешний chat model baseline: `gemini-2.5-flash` (или актуальный free Flash из AI Studio на момент реализации).

Что идёт наружу в E2.1:

- **только chat / RAG generation** (user-selected model + `approach=openapi|hybrid`);
- **embeddings** остаются на Ollama (`nomic-embed-text`) — иначе ломается размерность Qdrant;
- **vision / image digest / targeted vision** остаются на Ollama;
- **conversation summary** остаётся на Ollama.

Routing `approach` (уже есть во frontend, backend начнёт использовать):

| Approach | Chat generation | Embeddings / vision / summary |
|----------|-----------------|-------------------------------|
| `local_only` | Ollama | Ollama |
| `openapi` | Gemini | Ollama |
| `hybrid` | Ollama primary, fallback на Gemini при outage/overload | Ollama |

Официального free OpenAI key нет — для pet/portfolio baseline берём Gemini free tier, не shared/leaked OpenAI keys.

Future hardening (не E2.1):

- OpenRouter / Groq как дополнительные OpenAI-compatible backends;
- external vision/embeddings;
- per-tenant model allowlist в DB;
- cost accounting.

Scope E2.1:

- abstraction `LLMProvider` (`generate`, `embed`, `health`);
- `OllamaProvider` (wrap текущего `OllamaClient`);
- `OpenAICompatibleProvider` (Gemini baseline);
- `ModelGateway` / registry: resolve `(model_id, approach, tenant)` → provider + concrete model;
- wiring в `POST /chat` и `POST /rag/chat`;
- audit: реальный `provider` в chat metadata / logs;
- unit tests + smoke с `GEMINI_API_KEY`.

Заметки по fine-tuning:

- local LoRA/QLoRA остаётся правильным путём для open-weight models;
- closed external models обычно нельзя дообучать через LoRA, потому что weights недоступны;
- external fine-tuning provider-specific и должен идти через отдельный provider adapter.

Definition of done (E2.1):

- пользователь может выбрать local Ollama chat или Gemini chat через `approach` / model list;
- embeddings/vision не зависят от Gemini;
- при `hybrid` и недоступном Ollama chat возможен fallback на Gemini;
- все chat generation calls логируются с `provider`, `model`, `request_id`.

## Этап E3: Agents, Function Calling And Tool Use

Статус: **done** (2026-07-14) — controlled tools + agent loop baseline. E2 остаётся blocked (VPN).

Цель:

- вынести существующие backend-возможности как controlled tools с registry, RBAC matrix, audit и portable JSON tool loop.

Baseline tools (E3.1–E3.2):

- `get_user_context`;
- `list_buckets`;
- `get_document_status`;
- `rag_search`;
- `text_to_sql` (LoRA default + fallback);
- `execute_readonly_sql`.

Delivered:

- E3.1 tool registry/executor/`ToolResult`/role matrix + audit `tool_call_logs`;
- E3.2 allowlisted readonly SQL + LoRA model fallback;
- E3.3 `POST /agent/chat` + AgentOrchestrator + UI mode Agent + tool-trace panel;
- E3.4 V5 LoRA packaged as Ollama tag `qwen2_5_coder_7b_v5_projection_steps400` (adapter GGUF path; smoke без fallback).

Later / out of scope сейчас:

- `ingest_document`;
- `generate_report`;
- `send_email_summary`;
- auto-retry framework;
- native OpenAI/Gemini function-calling adapter (после E2 VPN).

Правила:

- tools сами enforce RBAC и tenant/document filters до side effects;
- единый `ToolResult` (`ok` / `denied` / `invalid_input` / `failed`);
- tool inputs — Pydantic schemas; role matrix явная;
- tool calls аудируются (`metadata.tool_calls` + `tool_call_logs`);
- conversation memory — в prompt оркестратора, не внутри tools;
- agent output остаётся grounded в retrieved/tool-produced evidence.

Definition of done:

- agent chat может вызвать как минимум `rag_search` и Text-to-SQL path — **done**;
- unauthorized/invalid tool calls → `ToolResult` до execution — **done**;
- tool call trace виден в API metadata и UI — **done**;
- viewer не execute SQL; document no-leak сохраняется — **done**.

### E3.4: LoRA → Ollama tag

Статус: **done** — tag `qwen2_5_coder_7b_v5_projection_steps400` в Ollama; `TextToSqlService` smoke с `fallback_used=false`.

Почему не «просто Modelfile ADAPTER» на safetensors: V5 adapter — PEFT на **Qwen2.5-Coder**; Ollama safetensors-ADAPTER официально покрывает Llama/Mistral/Gemma, не Qwen. Рабочий путь: **adapter → GGUF LoRA** (`convert_lora_to_gguf.py`) + Modelfile `FROM qwen2.5-coder:7b` + `ADAPTER …lora.gguf` (скрипт `backend/scripts/package_text_to_sql_lora_ollama.py`; полный merge — fallback). Детали: `.cursor/plans/e3_tools_agents_201ce1e6.plan.md` § E3.4.

## Этап E4: n8n And Email/Workflow Integration

Цель:

- принимать внешний business content через workflow automation.

Scope:

- n8n workflows для email/webhook/document ingestion;
- Gmail integration через OAuth2/Gmail API;
- Yandex/corporate mail через IMAP/API, где это практично;
- Outlook/Microsoft 365 через Microsoft Graph;
- optional Outlook add-in как future UI extension.

Definition of done:

- n8n может принять или скачать document и вызвать backend ingestion endpoint;
- загруженный контент попадает в tenant/bucket с трассируемым metadata;
- статус ingestion и ошибки видны.

## Этап E5: Kafka And Event-Driven Ingestion

Цель:

- поддержать high-volume document и evaluation workloads через durable event streams.

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

- document ingestion может работать асинхронно через events;
- processing state остаётся persisted в PostgreSQL;
- failed events можно retry-ить или inspect-ить;
- Kafka используется для durable workflow events, а Redis остаётся полезен для rate limits и lightweight coordination.

## Этап E6: Framework Adapters

Цель:

- точечно использовать LangGraph/LangChain/LlamaIndex/CrewAI там, где они дают ценность.

Рекомендуемый подход:

- LangGraph для явных agent workflows и tool routing;
- LlamaIndex для connectors или retrieval experiments;
- LangChain для provider/tool abstractions, когда это полезно;
- CrewAI только для ограниченных multi-agent demos, не для ownership core backend.

Definition of done:

- framework integration вызывает текущие backend services, а не заменяет их;
- evaluation scenarios подтверждают, что framework layer не обходит access controls.

## Этап E7: Product Hardening

Цель:

- сделать приложение demoable как продукт, а не как набор backend scripts.

Scope:

- deployment profiles;
- object storage для uploaded files;
- более сильное admin/tenant management;
- observability dashboards;
- audit export;
- user-facing report generation;
- regression suite, покрывающий UI, auth, RAG, Text-to-SQL и ingestion.

## Рекомендуемый порядок

1. E0 UI Skeleton — **done**.
2. E1 Keycloak/BFF/RBAC — **done** (2026-07-14).
3. E2 Model Gateway и external providers — **blocked** (VPN / Gemini unreachable; kickoff сохранён).
4. E3 Tool-use/agents — **done** (2026-07-14).
5. E4 n8n/email workflows.
6. E5 Kafka event backbone.
7. E6 framework adapters.
8. E7 product hardening.

Такой порядок сначала даёт видимую product surface, а затем постепенно заменяет mocks enterprise-grade инфраструктурой.
