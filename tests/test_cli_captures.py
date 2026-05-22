"""CLI tests for ``lp capture`` subcommands."""

from __future__ import annotations

import psycopg
import pytest
from typer.testing import CliRunner

from luplo.cli import app

runner = CliRunner()

_CLI_PROJECT = "cli-captures-test-project"
_CLI_ACTOR = "00000000-0000-0000-0000-0000000000c3"


@pytest.fixture
def env(db_url: str) -> dict[str, str]:
    return {
        "LUPLO_DB_URL": db_url,
        "LUPLO_PROJECT": _CLI_PROJECT,
        "LUPLO_ACTOR_ID": _CLI_ACTOR,
    }


@pytest.fixture(autouse=True)
def _seed(db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO projects (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (_CLI_PROJECT, "CLI Captures Test"),
        )
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


def test_capture_find(env: dict[str, str]) -> None:
    import uuid

    token = f"family{uuid.uuid4().hex}"
    runner.invoke(app, ["capture", "add", "family dinner reaction", token], env=env)
    runner.invoke(app, ["capture", "add", "game combat idea"], env=env)

    result = runner.invoke(app, ["capture", "find", token], env=env)

    assert result.exit_code == 0, result.output
    assert "family dinner reaction" in result.output
    assert "game combat idea" not in result.output


def test_capture_state_and_discard(env: dict[str, str]) -> None:
    added = runner.invoke(app, ["capture", "add", "discard target"], env=env)
    capture_id = added.output.split("Saved capture: ", 1)[1][:8]

    state_result = runner.invoke(app, ["capture", "state", capture_id, "backlog"], env=env)
    assert state_result.exit_code == 0, state_result.output
    assert "backlog" in state_result.output

    discard_result = runner.invoke(app, ["capture", "discard", capture_id], env=env)
    assert discard_result.exit_code == 0, discard_result.output
    assert "discarded" in discard_result.output

    listed = runner.invoke(app, ["capture", "ls"], env=env)
    assert "discard target" not in listed.output


def test_capture_redact_masks_content(env: dict[str, str]) -> None:
    added = runner.invoke(app, ["capture", "add", "sensitive raw phrase"], env=env)
    capture_id = added.output.split("Saved capture: ", 1)[1][:8]

    result = runner.invoke(app, ["capture", "redact", capture_id], env=env)
    assert result.exit_code == 0, result.output
    assert "redacted" in result.output

    listed = runner.invoke(app, ["capture", "ls", "--include-redacted"], env=env)
    assert "sensitive raw phrase" not in listed.output
    assert "[redacted]" in listed.output

    found = runner.invoke(
        app, ["capture", "find", "sensitive", "raw", "phrase", "--include-redacted"], env=env
    )
    assert "sensitive raw phrase" not in found.output
    assert "No captures matched." in found.output


def test_capture_annotate(env: dict[str, str]) -> None:
    added = runner.invoke(app, ["capture", "add", "annotation target"], env=env)
    capture_id = added.output.split("Saved capture: ", 1)[1][:8]

    result = runner.invoke(
        app,
        [
            "capture",
            "annotate",
            capture_id,
            "--summary",
            "summary text",
            "--sensitivity-hint",
            "possible",
            "--signals",
            '{"tags":["people_issue"]}',
        ],
        env=env,
    )

    assert result.exit_code == 0, result.output
    assert "Annotated capture" in result.output

    found = runner.invoke(app, ["capture", "find", "summary", "text"], env=env)
    assert found.exit_code == 0, found.output
    assert "annotation target" in found.output


def test_capture_annotate_rejects_invalid_signals_json(env: dict[str, str]) -> None:
    added = runner.invoke(app, ["capture", "add", "bad signals target"], env=env)
    capture_id = added.output.split("Saved capture: ", 1)[1][:8]

    result = runner.invoke(
        app,
        ["capture", "annotate", capture_id, "--signals", "["],
        env=env,
    )

    assert result.exit_code == 2
    assert "invalid JSON for --signals" in result.output


def test_capture_promote_creates_item(env: dict[str, str]) -> None:
    added = runner.invoke(app, ["capture", "add", "promote me"], env=env)
    capture_id = added.output.split("Saved capture: ", 1)[1][:8]

    result = runner.invoke(
        app,
        [
            "capture",
            "promote",
            capture_id,
            "--type",
            "knowledge",
            "--title",
            "Promoted capture",
            "--body",
            "promote me",
        ],
        env=env,
    )

    assert result.exit_code == 0, result.output
    assert "Promoted capture" in result.output

    items = runner.invoke(app, ["items", "search", "promote"], env=env)
    assert items.exit_code == 0, items.output
    assert "Promoted capture" in items.output

    captures = runner.invoke(app, ["capture", "ls", "--state", "promoted"], env=env)
    assert captures.exit_code == 0, captures.output
    assert "promote me" in captures.output
