# ---------------------------------------------------------------------------
# One-shot local environment setup (Windows PowerShell).
#
# Usage (from the project root, in PowerShell):
#   .\scripts\setup.ps1
#
# If script execution is blocked, run PowerShell as Administrator once:
#   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
# ---------------------------------------------------------------------------

Write-Host "==> Creating virtual environment (.venv)"
python -m venv .venv

Write-Host "==> Activating virtual environment"
. .\.venv\Scripts\Activate.ps1

Write-Host "==> Upgrading pip"
python -m pip install --upgrade pip

Write-Host "==> Installing runtime + dev dependencies"
pip install -r requirements.txt -r requirements-dev.txt

if (-Not (Test-Path ".env")) {
    Write-Host "==> Creating .env from .env.example"
    Copy-Item ".env.example" ".env"
    Write-Host "    Edit .env and set SECURITY_JWT_SECRET_KEY and any LLM API keys before running."
} else {
    Write-Host "==> .env already exists, leaving it untouched"
}

Write-Host ""
Write-Host "Setup complete. Next steps:"
Write-Host "  1. docker compose up -d           # start Postgres/Redis/RabbitMQ/Qdrant"
Write-Host "  2. .\.venv\Scripts\Activate.ps1    # if not already active"
Write-Host "  3. alembic upgrade head             # initialize/update schema from migrations"
Write-Host "  4. uvicorn app.main:app --reload   # start the API"
Write-Host "  5. pytest                          # run the test suite"
