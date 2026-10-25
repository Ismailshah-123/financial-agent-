#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# One-shot local environment setup (Linux / macOS / WSL).
# Windows users: see scripts/setup.ps1 instead.
#
# Usage:
#   chmod +x scripts/setup.sh
#   ./scripts/setup.sh
# ---------------------------------------------------------------------------
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "==> Creating virtual environment (.venv)"
"$PYTHON_BIN" -m venv .venv

echo "==> Activating virtual environment"
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Upgrading pip"
pip install --upgrade pip

echo "==> Installing runtime + dev dependencies"
pip install -r requirements.txt -r requirements-dev.txt

if [ ! -f .env ]; then
  echo "==> Creating .env from .env.example"
  cp .env.example .env
  echo "    Edit .env and set SECURITY_JWT_SECRET_KEY and any LLM API keys before running."
else
  echo "==> .env already exists, leaving it untouched"
fi

echo ""
echo "Setup complete. Next steps:"
echo "  1. docker compose up -d          # start Postgres/Redis/RabbitMQ/Qdrant"
echo "  2. source .venv/bin/activate      # if not already active"
echo "  3. python -m app.db.init_db       # create tables (dev only; use Alembic later)"
echo "  4. uvicorn app.main:app --reload  # start the API"
echo "  5. pytest                         # run the test suite"
