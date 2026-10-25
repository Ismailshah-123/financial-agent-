"""Regression tests for how configuration is loaded from `.env`.

Defect: only the root `Settings` class named an `env_file`. Each nested group (database, security,
SAP, ...) is its own `BaseSettings` and does not inherit it, so a developer's `.env` was silently
ignored and only real environment variables took effect. Blank lines copied from `.env.example`
(for example `SAP_SERVICE_LAYER_URL=`) would also have failed validation once the file was read.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_settings import BaseSettings

from app.core import config


def _groups() -> list[tuple[str, type[BaseSettings]]]:
    found = []
    for name, field in config.Settings.model_fields.items():
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseSettings):
            found.append((name, annotation))
    return found


def test_there_are_settings_groups_to_check() -> None:
    assert len(_groups()) >= 9


def test_every_settings_group_reads_the_project_dotenv() -> None:
    root_env_file = config.Settings.model_config.get("env_file")
    assert root_env_file is not None
    for name, group in _groups():
        assert group.model_config.get("env_file") == root_env_file, name
        assert group.model_config.get("env_ignore_empty") is True, name
        assert group.model_config.get("extra") == "ignore", name


def test_env_file_is_anchored_to_the_repository_root_not_the_working_directory() -> None:
    env_file = Path(str(config.Settings.model_config["env_file"]))
    assert env_file.is_absolute()
    assert env_file.name == ".env"
    assert (env_file.parent / "alembic.ini").exists()


def test_values_in_a_dotenv_file_reach_their_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("DB_NAME", "DB_HOST", "APP_DEBUG"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("DB_NAME=from_dotenv_file\nDB_HOST=db.internal\nAPP_DEBUG=true\n")

    database = config.DatabaseSettings(_env_file=env_file)
    app = config.AppSettings(_env_file=env_file)

    assert database.name == "from_dotenv_file"
    assert database.host == "db.internal"
    assert app.debug is True


def test_blank_optional_lines_from_env_example_do_not_break_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("SAP_SERVICE_LAYER_URL", "SAP_COMPANY_DB", "LLM_GROQ_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("SAP_SERVICE_LAYER_URL=\nSAP_COMPANY_DB=\nLLM_GROQ_API_KEY=\n")

    sap = config.SAPSettings(_env_file=env_file)
    llm = config.LLMSettings(_env_file=env_file)

    assert sap.service_layer_url is None
    assert sap.company_db is None
    assert llm.groq_api_key is None


def test_a_real_environment_variable_still_beats_the_dotenv_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DB_NAME=from_dotenv_file\n")
    monkeypatch.setenv("DB_NAME", "from_real_environment")

    assert config.DatabaseSettings(_env_file=env_file).name == "from_real_environment"
