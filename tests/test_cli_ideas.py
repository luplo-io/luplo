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
    # newest-first ordering
    assert result.output.index("thought two") < result.output.index("thought one")


def test_idea_add_accepts_wu_hex_prefix(env: dict[str, str], db_url: str) -> None:
    """--wu accepts an 8-char hex prefix (CLI help promises this)."""
    wu_id = _seed_wu(db_url)
    result = runner.invoke(app, ["idea", "add", "via prefix", "--wu", wu_id[:8]], env=env)
    assert result.exit_code == 0, result.output


def test_idea_ls_accepts_wu_hex_prefix(env: dict[str, str], db_url: str) -> None:
    wu_id = _seed_wu(db_url)
    runner.invoke(app, ["idea", "add", "row", "--wu", wu_id], env=env)
    result = runner.invoke(app, ["idea", "ls", "--wu", wu_id[:8]], env=env)
    assert result.exit_code == 0, result.output
    assert "row" in result.output


def test_idea_ls_uses_active_wu_when_omitted(env: dict[str, str], db_url: str) -> None:
    """--wu is optional on `lp idea ls` and falls back to the active WU."""
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "UPDATE work_units SET status='done', closed_at=now()"
            " WHERE project_id=%s AND status='in_progress'",
            (_CLI_PROJECT,),
        )
        conn.commit()
    wu_id = _seed_wu(db_url, title="ls-active")
    runner.invoke(app, ["idea", "add", "implicit-ls thought", "--wu", wu_id], env=env)
    result = runner.invoke(app, ["idea", "ls"], env=env)
    assert result.exit_code == 0, result.output
    assert "implicit-ls thought" in result.output


def test_idea_find_filter_only_no_query(env: dict[str, str], db_url: str) -> None:
    """`lp idea find` accepts no positional query — author/since/etc filter alone."""
    wu_id = _seed_wu(db_url, title="filter-only")
    runner.invoke(app, ["idea", "add", "filter-only target", "--wu", wu_id], env=env)
    result = runner.invoke(app, ["idea", "find", "--wu", wu_id], env=env)
    assert result.exit_code == 0, result.output
    assert "filter-only target" in result.output


def test_idea_find_garbage_since_helpful_error(env: dict[str, str], db_url: str) -> None:
    """Bad --since value names the supported dialects."""
    result = runner.invoke(app, ["idea", "find", "x", "--since", "yesterday"], env=env)
    assert result.exit_code != 0
    out = result.output.lower()
    assert "since" in out or "dialect" in out or "iso" in out


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
    add_result = runner.invoke(
        app, ["idea", "add", "secret password content", "--wu", wu_id], env=env
    )
    assert add_result.exit_code == 0
    # Pull the 8-char id from output: "Added idea: <id8> (work_unit: <wu8>)"
    import re

    m = re.search(r"Added idea: ([0-9a-f]{8})", add_result.output)
    assert m, add_result.output
    idea_short = m.group(1)

    redact_result = runner.invoke(app, ["idea", "redact", idea_short], env=env)
    assert redact_result.exit_code == 0, redact_result.output
    assert "Redacted" in redact_result.output

    ls_result = runner.invoke(app, ["idea", "ls", "--wu", wu_id], env=env)
    assert "secret password" not in ls_result.output

    # Round 2 B4: --include-redacted surfaces the row's existence (id +
    # timestamp + REDACTED marker) but the original text is masked. The
    # MCP/CLI surface is not an admin path; raw redacted content is
    # only available via SaaS-side admin tools.
    ls_all = runner.invoke(app, ["idea", "ls", "--wu", wu_id, "--include-redacted"], env=env)
    assert ls_all.exit_code == 0, ls_all.output
    assert "secret password" not in ls_all.output  # body masked
    assert "[redacted]" in ls_all.output  # mask placeholder
    assert "REDACTED" in ls_all.output  # status marker still present


def test_idea_redact_idempotent_marks_already_redacted(
    env: dict[str, str], db_url: str
) -> None:
    """Round 2 S2: second redact reports 'Already redacted' instead of
    silently re-stamping (and the audit log only records one entry).
    """
    import re

    wu_id = _seed_wu(db_url)
    add_result = runner.invoke(app, ["idea", "add", "x", "--wu", wu_id], env=env)
    m = re.search(r"Added idea: ([0-9a-f]{8})", add_result.output)
    assert m, add_result.output
    idea_short = m.group(1)

    first = runner.invoke(app, ["idea", "redact", idea_short], env=env)
    assert first.exit_code == 0
    assert first.output.startswith("Redacted ")

    second = runner.invoke(app, ["idea", "redact", idea_short], env=env)
    assert second.exit_code == 0
    assert second.output.startswith("Already redacted ")


def test_idea_redact_bogus_id_clean_error(env: dict[str, str], db_url: str) -> None:
    """Round 2 B5: a bogus full UUID surfaces as a clean error, not a
    Python traceback — domain errors get translated by ``_run``.
    """
    bogus = "00000000-0000-0000-0000-0000000000ff"
    result = runner.invoke(app, ["idea", "redact", bogus], env=env)
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "not found" in result.output.lower()
    # Python traceback markers must not appear.
    assert "Traceback" not in result.output


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
