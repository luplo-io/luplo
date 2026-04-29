"""Tests for the ``lp migrate`` CLI command.

The command must work without a ``.luplo`` config file present (production
deploys run it in a container with only env vars). Connection errors are
out of scope here — we exercise the wiring (env-var pickup, --db-url
flag, error message on missing input) and trust the alembic-level
behaviour, which is covered by the integration suite.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from typer.testing import CliRunner

from luplo.cli import app

runner = CliRunner()


def test_migrate_uses_env_var_when_no_flag(tmp_path: Any, monkeypatch: Any) -> None:
    """``LUPLO_DB_URL`` env is forwarded to ``run_upgrade_head``."""
    monkeypatch.chdir(tmp_path)  # no .luplo present
    monkeypatch.setenv("LUPLO_DB_URL", "postgresql://example/db")
    with patch("luplo._migrate.run_upgrade_head") as m:
        result = runner.invoke(app, ["migrate"])
    assert result.exit_code == 0, result.output
    m.assert_called_once_with("postgresql://example/db")


def test_migrate_flag_overrides_env(tmp_path: Any, monkeypatch: Any) -> None:
    """``--db-url`` wins over ``LUPLO_DB_URL``."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LUPLO_DB_URL", "postgresql://from-env/db")
    with patch("luplo._migrate.run_upgrade_head") as m:
        result = runner.invoke(app, ["migrate", "--db-url", "postgresql://from-flag/db"])
    assert result.exit_code == 0, result.output
    m.assert_called_once_with("postgresql://from-flag/db")


def test_migrate_no_input_exits_one(tmp_path: Any, monkeypatch: Any) -> None:
    """Missing both env and flag yields a clean Exit(1) and an explainer."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LUPLO_DB_URL", raising=False)
    result = runner.invoke(app, ["migrate"])
    assert result.exit_code == 1
    assert "no database URL" in result.output


def test_migrate_no_dotluplo_required(tmp_path: Any, monkeypatch: Any) -> None:
    """``lp migrate`` must not call ``load_config`` — verified by absence."""
    monkeypatch.chdir(tmp_path)  # cwd has no .luplo
    monkeypatch.setenv("LUPLO_DB_URL", "postgresql://example/db")
    with (
        patch("luplo._migrate.run_upgrade_head"),
        patch("luplo.config.load_config") as load_cfg,
    ):
        result = runner.invoke(app, ["migrate"])
    assert result.exit_code == 0, result.output
    load_cfg.assert_not_called()


def test_migrate_propagates_failure_as_exit_one(tmp_path: Any, monkeypatch: Any) -> None:
    """Alembic failures surface as Exit(1) with the exception text."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LUPLO_DB_URL", "postgresql://example/db")
    with patch("luplo._migrate.run_upgrade_head", side_effect=RuntimeError("boom")):
        result = runner.invoke(app, ["migrate"])
    assert result.exit_code == 1
    assert "Migration failed" in result.output
    assert "boom" in result.output
