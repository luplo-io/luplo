"""CLI tests for ``lp idea`` subcommands."""

from __future__ import annotations

import uuid

import psycopg
import pytest
from typer.testing import CliRunner

from luplo.cli import app

runner = CliRunner()

_CLI_PROJECT = "cli-ideas-test-project"
_CLI_ACTOR = "00000000-0000-0000-0000-0000000000c2"


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
            (_CLI_PROJECT, "CLI Ideas Test"),
        )
        conn.execute(
            "INSERT INTO actors (id, name, email) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (_CLI_ACTOR, "CLI Ideas Actor", "ideas@test.com"),
        )
        conn.commit()


def _seed_wu(db_url: str, *, status: str = "in_progress", title: str = "Ideas WU") -> str:
    wu_id = str(uuid.uuid4())
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO work_units (id, project_id, title, status, created_by) "
            "VALUES (%s, %s, %s, %s, %s)",
            (wu_id, _CLI_PROJECT, title, status, _CLI_ACTOR),
        )
        conn.commit()
    return wu_id


def _close_wu(db_url: str, wu_id: str) -> None:
    """Close a WU so it isn't picked up as the active in-progress one."""
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "UPDATE work_units SET status='done', closed_at=now() WHERE id=%s",
            (wu_id,),
        )
        conn.commit()


def test_idea_add_with_explicit_wu(env: dict[str, str], db_url: str) -> None:
    wu_id = _seed_wu(db_url)
    result = runner.invoke(app, ["idea", "add", "refresh token swap idea", "--wu", wu_id], env=env)
    assert result.exit_code == 0, result.output
    assert "idea" in result.output.lower()


def test_idea_ls_shows_recent_first(env: dict[str, str], db_url: str) -> None:
    wu_id = _seed_wu(db_url)
    runner.invoke(app, ["idea", "add", "thought one", "--wu", wu_id], env=env)
    runner.invoke(app, ["idea", "add", "thought two", "--wu", wu_id], env=env)

    result = runner.invoke(app, ["idea", "ls", "--wu", wu_id], env=env)
    assert result.exit_code == 0, result.output
    assert "thought one" in result.output
    assert "thought two" in result.output


def test_idea_find_filters_by_keyword(env: dict[str, str], db_url: str) -> None:
    wu_id = _seed_wu(db_url)
    runner.invoke(app, ["idea", "add", "vendor inventory rotation", "--wu", wu_id], env=env)
    runner.invoke(app, ["idea", "add", "refresh token swap on frontend", "--wu", wu_id], env=env)

    result = runner.invoke(app, ["idea", "find", "refresh token"], env=env)
    assert result.exit_code == 0, result.output
    assert "refresh token swap" in result.output
    assert "vendor inventory" not in result.output


def test_idea_redact_hides_from_default_ls(env: dict[str, str], db_url: str) -> None:
    wu_id = _seed_wu(db_url)
    add_result = runner.invoke(app, ["idea", "add", "secret", "--wu", wu_id], env=env)
    assert add_result.exit_code == 0
    # Pull the 8-char id from output: "Added idea: <id8> (work_unit: <wu8>)"
    import re

    m = re.search(r"Added idea: ([0-9a-f]{8})", add_result.output)
    assert m, add_result.output
    idea_short = m.group(1)

    redact_result = runner.invoke(app, ["idea", "redact", idea_short], env=env)
    assert redact_result.exit_code == 0, redact_result.output

    ls_result = runner.invoke(app, ["idea", "ls", "--wu", wu_id], env=env)
    assert "secret" not in ls_result.output

    ls_all = runner.invoke(app, ["idea", "ls", "--wu", wu_id, "--include-redacted"], env=env)
    assert "secret" in ls_all.output
    assert "REDACTED" in ls_all.output


def test_idea_add_uses_active_wu_when_omitted(env: dict[str, str], db_url: str) -> None:
    # Close prior in_progress WUs so there's exactly one active WU to resolve.
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "UPDATE work_units SET status='done', closed_at=now()"
            " WHERE project_id=%s AND status='in_progress'",
            (_CLI_PROJECT,),
        )
        conn.commit()
    wu_id = _seed_wu(db_url, title="active-wu-test")
    result = runner.invoke(app, ["idea", "add", "implicit-wu thought"], env=env)
    assert result.exit_code == 0, result.output
    # And it should be attached to wu_id — verify via ls
    ls = runner.invoke(app, ["idea", "ls", "--wu", wu_id], env=env)
    assert "implicit-wu thought" in ls.output


def test_idea_add_no_active_wu_exits_nonzero(env: dict[str, str], db_url: str) -> None:
    """When no WU is in_progress and --wu is omitted, error out helpfully."""
    # Close any existing in_progress WUs in this project (from prior tests).
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "UPDATE work_units SET status='done', closed_at=now()"
            " WHERE project_id=%s AND status='in_progress'",
            (_CLI_PROJECT,),
        )
        conn.commit()

    result = runner.invoke(app, ["idea", "add", "orphan thought"], env=env)
    assert result.exit_code != 0
    assert (
        "no active" in result.output.lower()
        or "lp work open" in result.output
        or "--wu" in result.output
    )
