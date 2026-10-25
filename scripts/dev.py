#!/usr/bin/env python3
"""
scripts/dev.py
================
One command local development helper. Standard library only, works on Windows, macOS and Linux.

    python scripts/dev.py setup            create .venv, install everything, write .env, create the
                                           databases, run migrations, install the frontend
    python scripts/dev.py check            run every check and print ONE pass / fail table
    python scripts/dev.py check --fix      same, but let Black and Ruff rewrite formatting first
    python scripts/dev.py check --e2e      also run the browser tests (starts the web app itself)
    python scripts/dev.py run              start the API (8000) and the web app (3000) together
    python scripts/dev.py user --email you@company.com --full-name "Your Name" --role finance_director

`check` writes the full output of every step to verify-report.txt so one file is enough to diagnose
a failure. Nothing here changes application behaviour; it only runs the same commands the README
and CI describe.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
REPORT = ROOT / "verify-report.txt"
IS_WINDOWS = os.name == "nt"
VENV_PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
PLACEHOLDER_SECRET = "CHANGE_ME_IN_PRODUCTION"


# --------------------------------------------------------------------------- pure helpers
def render_env(example_text: str, secret: str) -> str:
    """Turn .env.example into a working local .env.

    * the JWT placeholder becomes a random secret
    * trailing "# comment" text after a value is dropped so every parser reads the value alone
    """
    lines = []
    for line in example_text.splitlines():
        if line.startswith("#") or "=" not in line:
            lines.append(line)
            continue
        key, _, value = line.partition("=")
        value = re.sub(r"\s+#.*$", "", value).rstrip() if not value.lstrip().startswith(('"', "'", "[")) else value
        lines.append(f"{key}={value}")
    return "\n".join(lines).replace(PLACEHOLDER_SECRET, secret) + "\n"


@dataclass
class StepResult:
    name: str
    status: str  # PASS, FAIL, WARN, SKIP
    seconds: float = 0.0
    detail: str = ""


def render_summary(results: list[StepResult]) -> str:
    width = max([len(r.name) for r in results] + [4])
    rows = [f"{'STEP'.ljust(width)}  RESULT  TIME   NOTE", "-" * (width + 40)]
    for r in results:
        rows.append(f"{r.name.ljust(width)}  {r.status.ljust(6)}  {r.seconds:5.1f}s  {r.detail}")
    counts = {s: sum(1 for r in results if r.status == s) for s in ("PASS", "FAIL", "WARN", "SKIP")}
    rows.append("-" * (width + 40))
    rows.append(
        f"{counts['PASS']} passed, {counts['FAIL']} failed, {counts['WARN']} warnings, {counts['SKIP']} skipped"
    )
    return "\n".join(rows)


def port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ------------------------------------------------------------------------------ helpers
def say(message: str) -> None:
    print(f"\n==> {message}", flush=True)


def venv_python() -> str:
    if not VENV_PYTHON.exists():
        raise SystemExit("The virtual environment is missing. Run: python scripts/dev.py setup")
    return str(VENV_PYTHON)


def tool(name: str) -> str | None:
    """Path to node tooling (npm, npx), which is a .cmd shim on Windows."""
    return shutil.which(name)


def run(cmd: list[str], cwd: Path = ROOT, env: dict[str, str] | None = None, check: bool = True) -> int:
    merged = {**os.environ, **(env or {})}
    print("$ " + " ".join(cmd), flush=True)
    code = subprocess.call(cmd, cwd=str(cwd), env=merged)
    if check and code != 0:
        raise SystemExit(f"Command failed with exit code {code}: {' '.join(cmd)}")
    return code


# -------------------------------------------------------------------------------- setup
DB_SNIPPET = r"""
import sys
import psycopg2
from app.core.config import settings

d = settings.database
try:
    conn = psycopg2.connect(host=d.host, port=d.port, user=d.user,
                            password=d.password.get_secret_value(), dbname="postgres")
except Exception as exc:  # noqa: BLE001
    print(f"CANNOT_CONNECT {exc}")
    sys.exit(3)
conn.autocommit = True
cur = conn.cursor()
for name in (d.name, d.name + "_test"):
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
    if cur.fetchone():
        print(f"exists {name}")
    else:
        cur.execute(f'CREATE DATABASE "{name}"')
        print(f"created {name}")
"""


def cmd_setup(_: argparse.Namespace) -> None:
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11 or newer is required (3.12 is what the project is tested on).")
    if sys.version_info >= (3, 13):
        print("Note: this project pins libraries that are tested on Python 3.12. Newer versions may fail to install.")

    say("1/6 Creating the virtual environment (.venv)")
    if not VENV_PYTHON.exists():
        run([sys.executable, "-m", "venv", str(ROOT / ".venv")])
    else:
        print("already exists")

    say("2/6 Installing Python dependencies (a few minutes the first time)")
    py = venv_python()
    run([py, "-m", "pip", "install", "--upgrade", "pip"])
    run([py, "-m", "pip", "install", "-r", "requirements-dev.txt"])

    say("3/6 Writing .env")
    env_file = ROOT / ".env"
    if env_file.exists():
        print(".env already exists, leaving it alone")
    else:
        env_file.write_text(
            render_env((ROOT / ".env.example").read_text(encoding="utf-8"), secrets.token_urlsafe(48)),
            encoding="utf-8",
        )
        print("created .env with a random JWT secret")

    say("4/6 Creating the PostgreSQL databases")
    proc = subprocess.run([py, "-c", DB_SNIPPET], cwd=str(ROOT), capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    if proc.returncode == 3:
        raise SystemExit(
            "\nPostgreSQL could not be reached or refused the login.\n"
            f"  detail: {proc.stdout.strip()}\n"
            "  1. Make sure PostgreSQL is running (Windows: Services, 'postgresql-x64-NN'; or run\n"
            "     'docker compose up -d postgres' with Docker Desktop started).\n"
            "  2. Put the real postgres password in .env as DB_PASSWORD=..., then run setup again."
        )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit("Creating the databases failed.")

    say("5/6 Building the database tables (alembic upgrade head)")
    run([py, "-m", "alembic", "upgrade", "head"])

    say("6/6 Installing the web app (npm install)")
    npm = tool("npm")
    if npm is None:
        print("npm was not found. Install Node.js 20 or newer from https://nodejs.org and run: cd frontend; npm install")
    else:
        run([npm, "install"], cwd=FRONTEND)

    print(
        "\nSetup finished.\n"
        "  Create your login :  python scripts/dev.py user --email YOUR_EMAIL --full-name \"Your Name\" --role finance_director\n"
        "  Start everything  :  python scripts/dev.py run     then open http://localhost:3000\n"
        "  Check everything  :  python scripts/dev.py check\n"
    )


# --------------------------------------------------------------------------------- user
def cmd_user(args: argparse.Namespace) -> None:
    run([venv_python(), "scripts/create_user.py", "--email", args.email, "--full-name", args.full_name, "--role", args.role])


# ---------------------------------------------------------------------------------- run
def _pump(prefix: str, stream) -> None:  # type: ignore[no-untyped-def]
    for line in iter(stream.readline, ""):
        print(f"[{prefix}] {line.rstrip()}", flush=True)


def _stop(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    if IS_WINDOWS:
        subprocess.call(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        proc.terminate()


def cmd_run(_: argparse.Namespace) -> None:
    npm = tool("npm")
    if npm is None:
        raise SystemExit("npm was not found. Install Node.js first.")
    py = venv_python()
    jobs = {
        "api": ([py, "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"], ROOT),
        "web": ([npm, "run", "dev"], FRONTEND),
    }
    procs: dict[str, subprocess.Popen[str]] = {}
    say("Starting the API on http://localhost:8000 and the web app on http://localhost:3000 (Ctrl+C stops both)")
    for name, (cmd, cwd) in jobs.items():
        proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        procs[name] = proc
        threading.Thread(target=_pump, args=(name, proc.stdout), daemon=True).start()
    try:
        while all(p.poll() is None for p in procs.values()):
            time.sleep(0.5)
        dead = [n for n, p in procs.items() if p.poll() is not None]
        print(f"\n{', '.join(dead)} stopped unexpectedly. Scroll up for its error.")
    except KeyboardInterrupt:
        print("\nStopping…")
    finally:
        for p in procs.values():
            _stop(p)


# -------------------------------------------------------------------------------- check
@dataclass
class Step:
    name: str
    cmd: list[str]
    cwd: Path = ROOT
    env: dict[str, str] = field(default_factory=dict)
    advisory: bool = False  # a failure is reported as WARN, not FAIL
    needs: str | None = None  # "db" or "npm"


def _db_reachable() -> bool:
    return port_open(os.environ.get("DB_HOST", "localhost"), int(os.environ.get("DB_PORT", "5432")))


def execute(step: Step, log) -> StepResult:  # type: ignore[no-untyped-def]
    if step.needs == "db" and not _db_reachable():
        return StepResult(step.name, "SKIP", 0.0, "PostgreSQL is not reachable")
    if step.needs == "npm" and (tool("npm") is None or not (FRONTEND / "node_modules").exists()):
        return StepResult(step.name, "SKIP", 0.0, "run setup first (npm install)")
    started = time.time()
    log.write(f"\n{'=' * 78}\n$ {' '.join(step.cmd)}   (cwd {step.cwd})\n{'=' * 78}\n")
    try:
        proc = subprocess.run(
            step.cmd, cwd=str(step.cwd), env={**os.environ, **step.env}, capture_output=True, text=True, timeout=1800
        )
        output = proc.stdout + proc.stderr
        code = proc.returncode
    except FileNotFoundError as exc:
        output, code = str(exc), 127
    except subprocess.TimeoutExpired:
        output, code = "timed out after 30 minutes", 124
    log.write(output + f"\n[exit code {code}]\n")
    log.flush()
    seconds = time.time() - started
    if code == 0:
        return StepResult(step.name, "PASS", seconds)
    last = next((ln.strip() for ln in reversed(output.splitlines()) if ln.strip()), "")
    return StepResult(step.name, "WARN" if step.advisory else "FAIL", seconds, last[:70])


def build_steps(fix: bool, with_db: bool) -> list[Step]:
    py = str(VENV_PYTHON)
    npm = tool("npm") or "npm"
    steps: list[Step] = []
    if fix:
        steps.append(Step("backend: black (rewrite)", [py, "-m", "black", "app", "tests", "alembic", "scripts"]))
        steps.append(Step("backend: ruff (fix)", [py, "-m", "ruff", "check", ".", "--fix"]))
    steps += [
        Step("backend: compile", [py, "-m", "compileall", "-q", "app", "tests", "alembic", "scripts"]),
        Step("backend: unit tests", [py, "-m", "pytest", "tests/unit", "-q", "-p", "no:cacheprovider"]),
        Step("backend: black", [py, "-m", "black", "--check", "app", "tests", "alembic", "scripts"]),
        Step("backend: ruff", [py, "-m", "ruff", "check", "."]),
        Step("backend: mypy", [py, "-m", "mypy", "app"]),
        Step("backend: bandit", [py, "-m", "bandit", "-q", "-r", "app"], advisory=True),
    ]
    if with_db:
        test_env = {"APP_ENVIRONMENT": "test", "SECURITY_ALLOW_PUBLIC_REGISTRATION": "true"}
        steps += [
            Step("database: migrate test db", [py, "-m", "alembic", "upgrade", "head"], env={**test_env, "DB_NAME": _test_db_name()}, needs="db"),
            Step("backend: integration tests", [py, "-m", "pytest", "tests/integration", "-q", "-p", "no:cacheprovider"], env={**test_env, "DB_NAME": _test_db_name()}, needs="db"),
        ]
    steps += [
        Step("frontend: typecheck", [npm, "run", "typecheck"], FRONTEND, needs="npm"),
        Step("frontend: lint", [npm, "run", "lint"], FRONTEND, needs="npm"),
        Step("frontend: unit tests", [npm, "test"], FRONTEND, needs="npm"),
        Step("frontend: build", [npm, "run", "build"], FRONTEND, needs="npm"),
        Step("frontend: npm audit (high)", [npm, "audit", "--audit-level=high"], FRONTEND, advisory=True, needs="npm"),
    ]
    return steps


def _test_db_name() -> str:
    proc = subprocess.run(
        [str(VENV_PYTHON), "-c", "from app.core.config import settings; print(settings.database.name + '_test')"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    return proc.stdout.strip().splitlines()[-1] if proc.returncode == 0 and proc.stdout.strip() else "finance_ai_db_test"


def _run_e2e(log) -> StepResult:  # type: ignore[no-untyped-def]
    npm, npx = tool("npm"), tool("npx")
    if not npm or not npx or not (FRONTEND / "node_modules").exists():
        return StepResult("browser: e2e", "SKIP", 0.0, "run setup first")
    started = time.time()
    web = subprocess.Popen([npm, "run", "dev"], cwd=str(FRONTEND), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            if port_open("127.0.0.1", 3000):
                break
            time.sleep(1)
        else:
            return StepResult("browser: e2e", "FAIL", time.time() - started, "web app did not start on port 3000")
        install = subprocess.run([npx, "playwright", "install", "chromium"], cwd=str(FRONTEND), capture_output=True, text=True)
        log.write(f"\n{'=' * 78}\n$ npx playwright install chromium\n{'=' * 78}\n{install.stdout}{install.stderr}\n")
        proc = subprocess.run(
            [npx, "playwright", "test", "e2e/mocked.spec.ts", "e2e/accessibility.spec.ts"],
            cwd=str(FRONTEND), capture_output=True, text=True, timeout=1800,
            env={**os.environ, "E2E_BASE_URL": "http://127.0.0.1:3000"},
        )
        log.write(f"\n{'=' * 78}\n$ npx playwright test (mocked + accessibility)\n{'=' * 78}\n{proc.stdout}{proc.stderr}\n[exit code {proc.returncode}]\n")
        last = next((ln.strip() for ln in reversed((proc.stdout + proc.stderr).splitlines()) if ln.strip()), "")
        return StepResult("browser: e2e + accessibility", "PASS" if proc.returncode == 0 else "FAIL", time.time() - started, "" if proc.returncode == 0 else last[:70])
    finally:
        _stop(web)  # type: ignore[arg-type]


def cmd_check(args: argparse.Namespace) -> None:
    py = venv_python()
    print(f"Running every check. Full output goes to {REPORT.name}. This takes a few minutes.\n")
    results: list[StepResult] = []
    with REPORT.open("w", encoding="utf-8") as log:
        log.write(f"verify-report  python={sys.version.split()[0]}  platform={sys.platform}\n")
        for step in build_steps(fix=args.fix, with_db=not args.no_db):
            print(f"  running {step.name} …", flush=True)
            result = execute(step, log)
            results.append(result)
            print(f"    {result.status} {result.detail}", flush=True)
        if args.e2e:
            print("  running browser e2e …", flush=True)
            results.append(_run_e2e(log))
        summary = render_summary(results)
        log.write("\n\n" + summary + "\n")
    print("\n" + summary)
    print(f"\nFull details: {REPORT}")
    if any(r.status == "FAIL" for r in results):
        print("\nSome checks failed. Send me verify-report.txt (or the lines marked FAIL above) and I will fix them.")
        if not args.fix:
            print("Formatting failures can be repaired automatically with: python scripts/dev.py check --fix")
        raise SystemExit(1)
    _ = py


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local development helper for the Finance AI Platform.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="install everything and prepare the databases").set_defaults(func=cmd_setup)
    check = sub.add_parser("check", help="run every check and print one table")
    check.add_argument("--fix", action="store_true", help="let Black and Ruff rewrite formatting first")
    check.add_argument("--e2e", action="store_true", help="also run the browser tests")
    check.add_argument("--no-db", action="store_true", help="skip the PostgreSQL integration tests")
    check.set_defaults(func=cmd_check)
    sub.add_parser("run", help="start the API and the web app").set_defaults(func=cmd_run)
    user = sub.add_parser("user", help="create a login")
    user.add_argument("--email", required=True)
    user.add_argument("--full-name", required=True)
    user.add_argument("--role", required=True)
    user.set_defaults(func=cmd_user)
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
