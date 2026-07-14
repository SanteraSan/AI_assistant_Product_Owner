# Local Keycloak For TaskFlow AI

Local OIDC baseline for stage E1.

## Start

From the repository root:

```bash
docker compose up -d keycloak
```

Admin console:

- URL: http://localhost:8080
- user: `admin`
- password: `admin`

Compose uses `KC_BOOTSTRAP_ADMIN_USERNAME` / `KC_BOOTSTRAP_ADMIN_PASSWORD` for Keycloak 26.

Realm:

- `taskflow`
- OpenID discovery: http://localhost:8080/realms/taskflow/.well-known/openid-configuration

## Confidential Client

- client id: `taskflow-bff`
- client secret: `taskflow-bff-dev-secret`
- flow: Authorization Code + PKCE (`S256`)
- local-only secret; replace before any shared/demo deployment

## Test Users

Password for all local users: `ChangeMe123!`

| Username | Roles | `tenant_id` |
|----------|-------|-------------|
| `admin@local` | `admin`, `analyst`, `ingestion_manager`, `model_manager` | `local_demo` |
| `analyst@local` | `analyst` | `local_demo` |
| `viewer@local` | `viewer` | `local_demo` |

Token claims include:

- `tenant_id`
- `roles` (realm roles)

## Smoke Checks

```bash
curl -s http://localhost:8080/realms/taskflow/.well-known/openid-configuration | head
```

Password-grant smoke for local debugging only:

```bash
curl -s -X POST http://localhost:8080/realms/taskflow/protocol/openid-connect/token \
  -d 'grant_type=password' \
  -d 'client_id=taskflow-bff' \
  -d 'client_secret=taskflow-bff-dev-secret' \
  -d 'username=admin@local' \
  -d 'password=ChangeMe123!'
```

## Notes

- Keycloak runs in `start-dev` mode for local work.
- Dedicated Keycloak PostgreSQL and production hardening remain future work.
- Browser login for the product will go through the BFF, not a public SPA client.
