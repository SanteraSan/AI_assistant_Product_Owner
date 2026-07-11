#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

"$BACKEND_DIR/.venv/bin/python" -m pytest "$BACKEND_DIR/tests"

if command -v npm >/dev/null 2>&1; then
  (cd "$FRONTEND_DIR" && npm run build)
  (cd "$FRONTEND_DIR" && npm run lint)
else
  echo "npm not found. Skipping frontend build/lint."
fi
