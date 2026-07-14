# TaskFlow BFF

Session/OIDC edge for stage E1.

## Role

- Owns Keycloak Authorization Code + PKCE login
- Stores server-side session in Redis
- Issues short-lived signed service JWT to backend
- Proxies `/api/*` to backend
- Exposes `/auth/me` for frontend bootstrap

## Local Run

```bash
cd bff
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

Requirements:

- Keycloak running (`docker compose up -d keycloak`)
- Redis running (`docker compose up -d redis`)

## Endpoints

- `GET /auth/login`
- `GET /auth/callback`
- `GET /auth/me`
- `POST /auth/logout` (requires `X-CSRF-Token`)
- `ANY /api/{path}` -> backend with service JWT

## Tests

```bash
cd bff
source .venv/bin/activate
pytest -q
```
