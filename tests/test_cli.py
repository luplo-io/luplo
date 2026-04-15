"""Smoke tests for the CLI using typer's CliRunner."""

from __future__ import annotations

import uuid

import pytest
from typer.testing import CliRunner

from luplo.cli import app

runner = CliRunner()


@pytest.fixture
def env(db_url: str) -> dict[str, str]:
    """Environment variables needed for CLI commands."""
    return {
        "LUPLO_DB_URL": db_url,
        "LUPLO_PROJECT": "cli-test-project",
        "LUPLO_ACTOR_ID": "00000000-0000-0000-0000-0000000000c1",
    }


@pytest.fixture(autouse=True)
def _seed_cli_data(db_url: str) -> None:
    """Seed project + actor for CLI tests (sync, session-scoped DB)."""
    import psycopg

    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO projects (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            ("cli-test-project", "CLI Test"),
        )
        conn.execute(
            "INSERT INTO actors (id, name, email) VALUES (%s, %s, %s)"
            " ON CONFLICT DO NOTHING",
            ("00000000-0000-0000-0000-0000000000c1", "CLI Actor", "cli@test.com"),
        )
        conn.commit()


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "luplo" in result.output.lower()


def test_items_add(env: dict[str, str]) -> None:
    result = runner.invoke(app, ["items", "add", "Test decision"], env=env)
    assert result.exit_code == 0
    assert "Created" in result.output


def test_items_list(env: dict[str, str]) -> None:
    # Add an item first
    runner.invoke(app, ["items", "add", "Listed item"], env=env)

    result = runner.invoke(app, ["items", "list"], env=env)
    assert result.exit_code == 0
    assert "Listed item" in result.output


def test_items_search(env: dict[str, str]) -> None:
    runner.invoke(app, ["items", "add", "Searchable vendor decision"], env=env)

    result = runner.invoke(app, ["items", "search", "vendor"], env=env)
    assert result.exit_code == 0
    assert "vendor" in result.output.lower()


def test_work_open_and_close(env: dict[str, str]) -> None:
    result = runner.invoke(app, ["work", "open", "CLI sprint"], env=env)
    assert result.exit_code == 0
    assert "Opened" in result.output

    # Extract work unit ID from output
    # Output format: "Opened work unit [xxxxxxxx] CLI sprint"
    wu_id_prefix = result.output.split("[")[1].split("]")[0]

    # Get full ID via brief (which lists active work units)
    brief_result = runner.invoke(app, ["brief"], env=env)
    assert "CLI sprint" in brief_result.output


def test_systems_add_and_list(env: dict[str, str]) -> None:
    name = f"sys-{uuid.uuid4().hex[:6]}"
    result = runner.invoke(app, ["systems", "add", name], env=env)
    assert result.exit_code == 0
    assert "Created" in result.output

    result = runner.invoke(app, ["systems", "list"], env=env)
    assert result.exit_code == 0
    assert name in result.output


def test_brief(env: dict[str, str]) -> None:
    result = runner.invoke(app, ["brief"], env=env)
    assert result.exit_code == 0
    # Should show either active work units or "No active work units"
    assert "work units" in result.output.lower() or "items" in result.output.lower()


def test_glossary_ls_empty(env: dict[str, str]) -> None:
    result = runner.invoke(app, ["glossary", "ls"], env=env)
    assert result.exit_code == 0


def test_glossary_pending_empty(env: dict[str, str]) -> None:
    result = runner.invoke(app, ["glossary", "pending"], env=env)
    assert result.exit_code == 0
    assert "No pending" in result.output
