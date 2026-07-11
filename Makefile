PYTHON ?= python3
BACKEND_VENV := backend/.venv
BACKEND_PYTHON := $(BACKEND_VENV)/bin/python
BACKEND_PIP := $(BACKEND_VENV)/bin/pip
ALEMBIC := $(BACKEND_VENV)/bin/alembic

.PHONY: bootstrap backend-venv backend-test backend-migrate frontend-install frontend-build frontend-lint check dev-backend dev-frontend

bootstrap: backend-venv frontend-install

backend-venv:
	test -x "$(BACKEND_PYTHON)" || $(PYTHON) -m venv "$(BACKEND_VENV)"
	"$(BACKEND_PYTHON)" -m pip install -U pip
	"$(BACKEND_PIP)" install -r backend/requirements.txt
	test -f backend/.env || cp backend/.env.example backend/.env

backend-test:
	"$(BACKEND_PYTHON)" -m pytest backend/tests

backend-migrate:
	cd backend && "../$(ALEMBIC)" -c alembic.ini upgrade head

frontend-install:
	@if command -v npm >/dev/null 2>&1; then \
		cd frontend && npm install; \
	else \
		echo "npm not found. Install Node.js 24, then run: make frontend-install"; \
	fi

frontend-build:
	@if command -v npm >/dev/null 2>&1; then \
		cd frontend && npm run build; \
	else \
		echo "npm not found. Skipping frontend build."; \
	fi

frontend-lint:
	@if command -v npm >/dev/null 2>&1; then \
		cd frontend && npm run lint; \
	else \
		echo "npm not found. Skipping frontend lint."; \
	fi

check: backend-test frontend-build frontend-lint

dev-backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev
