# E4 n8n Integrations — Disk + External DB Slice

## Goal

Prove the integration seam:

```text
n8n (disk file + external Postgres rows)
  -> TaskFlow inbound API (service JWT)
  -> document indexing + allowlisted SQL sync
  -> Agent grounded via RAG + text_to_sql
```

n8n only delivers. ACL, indexing, and SQL validation stay in TaskFlow.

## E4.1 Implementation Map

| Piece | Location |
|-------|----------|
| Ingest API | `POST /integrations/ingest` |
| Sync API | `POST /integrations/sync-external-db` |
| Services | `integration_ingest_service.py`, `external_db_sync_service.py` |
| Allowlist tables | `external_customers`, `external_support_tickets` |
| Migration | `alembic/versions/20260714_0008_external_sync_tables.py` |
| External seed | `backend/scripts/seed_external_demo.py` |
| JWT helper | `backend/scripts/issue_integration_jwt.py` |
| Fixture | `data/integrations/inbox/external_integrations_brief.txt` |
| Workflow JSON | `data/integrations/n8n_workflow_e4_disk_and_db.json` |

## Local Run

1. Deps: see `research/E4_DEPENDENCIES.md` (n8n :5678, external PG :5433, inbox dir).
2. Seed external DB: `cd backend && python scripts/seed_external_demo.py`
3. Migrate / start backend (auto-create tables also covers models when enabled).
4. Issue JWT: `python scripts/issue_integration_jwt.py`
5. Curl smoke or import n8n workflow and set `TASKFLOW_SERVICE_JWT`.

## Curl Smoke

```bash
TOKEN=$(python scripts/issue_integration_jwt.py)
curl -sS -X POST http://localhost:8000/integrations/ingest \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-File-Name: external_integrations_brief.txt" \
  -H "X-Integration-Channel: disk" \
  -H "Content-Type: text/plain" \
  --data-binary @../data/integrations/inbox/external_integrations_brief.txt

curl -sS -X POST http://localhost:8000/integrations/sync-external-db \
  -H "Authorization: Bearer $TOKEN"
```

## Out of scope here

Email OAuth, Jira, direct agent→foreign DB, Kafka.
