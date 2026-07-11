# Development Environment

Проект использует два независимых runtime:

- backend: Python `3.14`, virtualenv в `backend/.venv`;
- frontend: Node.js `24`, зависимости в `frontend/node_modules`.

Python `.venv` не управляет Node/npm, поэтому frontend checks требуют отдельно установленный Node.js.

## Bootstrap

```bash
make bootstrap
```

Команда:

- создаёт `backend/.venv`, если его ещё нет;
- устанавливает `backend/requirements.txt`;
- создаёт `backend/.env` из `backend/.env.example`, если `.env` отсутствует;
- запускает `npm install`, если `npm` доступен.

То же самое можно запустить напрямую:

```bash
scripts/bootstrap_dev.sh
```

## Checks

```bash
make check
```

Команда запускает backend tests и frontend build/lint. Если `npm` не установлен, frontend checks будут пропущены с явным сообщением.

Отдельно:

```bash
make backend-test
make frontend-build
make frontend-lint
```

## Database Migrations

```bash
make backend-migrate
```

Эта команда применяет Alembic migrations из `backend/alembic`.

## Dev Servers

Backend:

```bash
make dev-backend
```

Frontend:

```bash
make dev-frontend
```

## Node.js

В корне проекта есть `.nvmrc`:

```bash
nvm install
nvm use
cd frontend
npm install
```

После этого `make check` будет запускать и frontend build/lint.
