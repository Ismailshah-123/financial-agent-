"""Tests for the pure helpers in scripts/dev.py (the one command local setup and check helper)."""

from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("dev_script", ROOT / "scripts" / "dev.py")
assert _spec and _spec.loader
dev = importlib.util.module_from_spec(_spec)
sys.modules["dev_script"] = dev
_spec.loader.exec_module(dev)


def test_env_template_gets_a_random_secret_and_clean_values() -> None:
    text = dev.render_env((ROOT / ".env.example").read_text(encoding="utf-8"), "s3cret-value-xyz")
    assert "CHANGE_ME_IN_PRODUCTION" not in text
    assert text.count("s3cret-value-xyz") == 1
    assert "\nAPP_ENVIRONMENT=local\n" in "\n" + text
    assert 'APP_CORS_ORIGINS=["http://localhost:3000"]' in text


def test_env_template_has_no_trailing_comments_on_value_lines() -> None:
    text = dev.render_env((ROOT / ".env.example").read_text(encoding="utf-8"), "x")
    for line in text.splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        value = line.partition("=")[2]
        if value.startswith(('"', "'", "[")):
            continue
        assert " #" not in value, line


def test_env_rendering_keeps_comments_and_blank_lines() -> None:
    sample = "# heading\n\nA=1   # note\nB=\"keep # inside\"\nC=[\"x\"]\n"
    assert dev.render_env(sample, "z") == "# heading\n\nA=1\nB=\"keep # inside\"\nC=[\"x\"]\n"


def test_summary_table_counts_each_outcome() -> None:
    results = [
        dev.StepResult("a", "PASS", 1.0),
        dev.StepResult("b", "FAIL", 2.5, "boom"),
        dev.StepResult("c", "WARN", 0.1),
        dev.StepResult("d", "SKIP", 0.0, "no db"),
    ]
    table = dev.render_summary(results)
    assert "1 passed, 1 failed, 1 warnings, 1 skipped" in table
    assert "boom" in table and "no db" in table


def test_execute_reports_pass_fail_and_missing_tools(tmp_path: Path) -> None:
    log = (tmp_path / "log.txt").open("w", encoding="utf-8")
    ok = dev.execute(dev.Step("ok", [sys.executable, "-c", "print(1)"]), log)
    bad = dev.execute(dev.Step("bad", [sys.executable, "-c", "import sys; sys.exit(3)"]), log)
    soft = dev.execute(dev.Step("soft", [sys.executable, "-c", "import sys; sys.exit(1)"], advisory=True), log)
    missing = dev.execute(dev.Step("missing", ["definitely-not-a-real-program"]), log)
    log.close()
    assert (ok.status, bad.status, soft.status, missing.status) == ("PASS", "FAIL", "WARN", "FAIL")
    assert "exit code 3" in (tmp_path / "log.txt").read_text(encoding="utf-8")


def test_port_probe_sees_open_and_closed_ports() -> None:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    open_port = server.getsockname()[1]
    assert dev.port_open("127.0.0.1", open_port)
    server.close()
    assert not dev.port_open("127.0.0.1", open_port, timeout=0.3)
