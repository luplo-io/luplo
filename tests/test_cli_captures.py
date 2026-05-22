"""CLI tests for ``lp capture`` subcommands."""

from __future__ import annotations

import psycopg
import pytest
from typer.testing import CliRunner

from luplo.cli import app

runner = CliRunner()

_CLI_ACTOR = "00000000-0000-0000-0000-0000000000c3"


@pytest.fixture
def env(db_url: str) -> dict[str, str]:
    return {
        "LUPLO_DB_URL": db_url,
        "LUPLO_ACTOR_ID": _CLI_ACTOR,
    }


@pytest.fixture(autouse=True)
def _seed(db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO actors (id, name, email) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (_CLI_ACTOR, "CLI Captures Actor", "captures@test.com"),
        )
        conn.commit()


def test_capture_add_and_ls(env: dict[str, str]) -> None:
    result = runner.invoke(
        app,
        ["capture", "add", "raw", "thought"],
        env=env,
    )

    assert result.exit_code == 0, result.output
    assert "Saved capture:" in result.output

    listed = runner.invoke(app, ["capture", "ls"], env=env)
    assert listed.exit_code == 0, listed.output
    assert "raw thought" in listed.output


def test_capture_add_rejects_empty(env: dict[str, str]) -> None:
    result = runner.invoke(app, ["capture", "add", "   "], env=env)

    assert result.exit_code == 2
    assert "capture text must not be empty" in result.output
