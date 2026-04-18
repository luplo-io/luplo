"""Smoke tests for the CLI using typer's CliRunner."""

from __future__ import annotations

import re
import uuid

import psycopg
import pytest
from typer.testing import CliRunner

from luplo.cli import app

runner = CliRunner()

_CLI_PROJECT = "cli-test-project"
_CLI_ACTOR = "00000000-0000-0000-0000-0000000000c1"


@pytest.fixture
def env(db_url: str) -> dict[str, str]:
    """Environment variables needed for CLI commands."""
    return {
        "LUPLO_DB_URL": db_url,
        "LUPLO_PROJECT": _CLI_PROJECT,
        "LUPLO_ACTOR_ID": _CLI_ACTOR,
    }


@pytest.fixture(autouse=True)
def _seed_cli_data(db_url: str) -> None:
    """Seed project + actor for CLI tests (sync, session-scoped DB)."""
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO projects (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (_CLI_PROJECT, "CLI Test"),
        )
        conn.execute(
            "INSERT INTO actors (id, name, email) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (_CLI_ACTOR, "CLI Actor", "cli@test.com"),
        )
        conn.commit()


def _seed_work_unit(db_url: str, title: str = "WU for CLI") -> str:
    """Insert a work unit directly and return its full UUID."""
    wu_id = str(uuid.uuid4())
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO work_units (id, project_id, title, status, created_by) "
            "VALUES (%s, %s, %s, 'in_progress', %s)",
            (wu_id, _CLI_PROJECT, title, _CLI_ACTOR),
        )
        conn.commit()
    return wu_id


def _seed_item(
    db_url: str,
    *,
    title: str = "Seed item",
    item_type: str = "decision",
    rationale: str | None = None,
) -> str:
    """Insert an item directly and return its full UUID."""
    item_id = str(uuid.uuid4())
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO items (id, project_id, item_type, title, rationale, actor_id, "
            "search_tsv) "
            "VALUES (%s, %s, %s, %s, %s, %s, to_tsvector('simple', %s))",
            (item_id, _CLI_PROJECT, item_type, title, rationale, _CLI_ACTOR, title),
        )
        conn.commit()
    return item_id


def _task_id_from_output(output: str) -> str:
    """Extract the 8-char task prefix from CLI output like '  abc12345  [proposed] ...'."""
    match = re.search(r"^\s{2,4}([0-9a-f]{8})\b", output, re.MULTILINE)
    assert match, f"no task id in output: {output!r}"
    return match.group(1)


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


# ── Items: show + list filters ──────────────────────────────────


def test_items_show(env: dict[str, str], db_url: str) -> None:
    item_id = _seed_item(db_url, title="Shown decision", rationale="because tests need this")
    result = runner.invoke(app, ["items", "show", item_id], env=env)
    assert result.exit_code == 0, result.output
    assert "Shown decision" in result.output
    assert "decision" in result.output


def test_items_show_not_found(env: dict[str, str]) -> None:
    result = runner.invoke(app, ["items", "show", str(uuid.uuid4())], env=env)
    assert result.exit_code == 1


def test_items_list_empty_filter(env: dict[str, str]) -> None:
    other_project = f"empty-{uuid.uuid4().hex[:6]}"
    # List in nonexistent project — hits the "No items found" branch.
    result = runner.invoke(app, ["items", "list", "--project", other_project], env=env)
    assert result.exit_code == 0
    assert "No items" in result.output


def test_items_search_no_results(env: dict[str, str]) -> None:
    unique_term = f"zzz{uuid.uuid4().hex[:8]}zzz"
    result = runner.invoke(app, ["items", "search", unique_term], env=env)
    assert result.exit_code == 0
    assert "No results" in result.output


# ── Work units ──────────────────────────────────────────────────


def test_work_resume_no_match(env: dict[str, str]) -> None:
    result = runner.invoke(app, ["work", "resume", f"nope-{uuid.uuid4().hex[:6]}"], env=env)
    assert result.exit_code == 0
    assert "No matching" in result.output


def test_work_resume_match(env: dict[str, str], db_url: str) -> None:
    _seed_work_unit(db_url, title="Resumable sprint")
    result = runner.invoke(app, ["work", "resume", "Resumable"], env=env)
    assert result.exit_code == 0
    assert "Resumable sprint" in result.output


def test_work_close_by_id(env: dict[str, str], db_url: str) -> None:
    wu_id = _seed_work_unit(db_url, title="To be closed")
    result = runner.invoke(app, ["work", "close", wu_id], env=env)
    assert result.exit_code == 0
    assert "Closed" in result.output


def test_work_close_not_found(env: dict[str, str]) -> None:
    result = runner.invoke(app, ["work", "close", str(uuid.uuid4())], env=env)
    # Missing work unit: exit != 0
    assert result.exit_code != 0


# ── Tasks ───────────────────────────────────────────────────────


def test_task_add_and_ls(env: dict[str, str], db_url: str) -> None:
    wu_id = _seed_work_unit(db_url, title="Task WU add/ls")
    r1 = runner.invoke(app, ["task", "add", "Draft spec", "--wu", wu_id, "--sort", "1"], env=env)
    assert r1.exit_code == 0, r1.output
    r2 = runner.invoke(app, ["task", "ls", "--wu", wu_id], env=env)
    assert r2.exit_code == 0
    assert "Draft spec" in r2.output


def test_task_ls_empty(env: dict[str, str], db_url: str) -> None:
    wu_id = _seed_work_unit(db_url, title="Empty WU")
    r = runner.invoke(app, ["task", "ls", "--wu", wu_id], env=env)
    assert r.exit_code == 0
    assert "No tasks" in r.output


def test_task_lifecycle(env: dict[str, str], db_url: str) -> None:
    """Create → show → start → in-progress → edit → done (with decision suggestion)."""
    wu_id = _seed_work_unit(db_url, title="Lifecycle WU")
    add_r = runner.invoke(
        app,
        [
            "task",
            "add",
            "Write tests",
            "--wu",
            wu_id,
            "--body",
            "initial body",
        ],
        env=env,
    )
    assert add_r.exit_code == 0, add_r.output
    tid = _task_id_from_output(add_r.output)

    show_r = runner.invoke(app, ["task", "show", tid], env=env)
    assert show_r.exit_code == 0
    assert "Write tests" in show_r.output

    start_r = runner.invoke(app, ["task", "start", tid], env=env)
    assert start_r.exit_code == 0
    assert "in_progress" in start_r.output

    # After start, task id may change (supersede chain). Get new id via ls.
    ls_r = runner.invoke(app, ["task", "ls", "--wu", wu_id], env=env)
    tid2 = _task_id_from_output(ls_r.output)

    ip_r = runner.invoke(app, ["task", "in-progress", "--wu", wu_id], env=env)
    assert ip_r.exit_code == 0
    assert "Write tests" in ip_r.output

    edit_r = runner.invoke(
        app,
        ["task", "edit", tid2, "--title", "Write more tests"],
        env=env,
    )
    assert edit_r.exit_code == 0, edit_r.output
    ls_r2 = runner.invoke(app, ["task", "ls", "--wu", wu_id], env=env)
    tid3 = _task_id_from_output(ls_r2.output)

    done_r = runner.invoke(
        app,
        [
            "task",
            "done",
            tid3,
            "--summary",
            "implemented",
            "--propose-decision",
        ],
        env=env,
    )
    assert done_r.exit_code == 0, done_r.output
    assert "done" in done_r.output.lower()


def test_task_blocked_and_skip(env: dict[str, str], db_url: str) -> None:
    wu_id = _seed_work_unit(db_url, title="Blocked WU")
    add_r = runner.invoke(app, ["task", "add", "Blocked work", "--wu", wu_id], env=env)
    tid = _task_id_from_output(add_r.output)
    blocked_r = runner.invoke(
        app,
        ["task", "blocked", tid, "--reason", "upstream dep missing"],
        env=env,
    )
    assert blocked_r.exit_code == 0, blocked_r.output

    skip_wu = _seed_work_unit(db_url, title="Skip WU")
    add2 = runner.invoke(app, ["task", "add", "Skip me", "--wu", skip_wu], env=env)
    tid2 = _task_id_from_output(add2.output)
    skip_r = runner.invoke(app, ["task", "skip", tid2, "--reason", "not needed"], env=env)
    assert skip_r.exit_code == 0


def test_task_start_collision(env: dict[str, str], db_url: str) -> None:
    """Starting a second task when one is in_progress fails cleanly."""
    wu_id = _seed_work_unit(db_url, title="Collision WU")
    add1 = runner.invoke(app, ["task", "add", "Task A", "--wu", wu_id], env=env)
    tid1 = _task_id_from_output(add1.output)
    runner.invoke(app, ["task", "start", tid1], env=env)

    add2 = runner.invoke(app, ["task", "add", "Task B", "--wu", wu_id], env=env)
    tid2 = _task_id_from_output(add2.output)
    collide = runner.invoke(app, ["task", "start", tid2], env=env)
    assert collide.exit_code != 0
    assert "in_progress" in collide.output.lower() or "error" in collide.output.lower()


# ── QA ──────────────────────────────────────────────────────────


def test_qa_lifecycle(env: dict[str, str], db_url: str) -> None:
    wu_id = _seed_work_unit(db_url, title="QA WU")
    add_r = runner.invoke(
        app,
        [
            "qa",
            "add",
            "Visual check",
            "--coverage",
            "human_only",
            "--area",
            "ux",
            "--wu",
            wu_id,
        ],
        env=env,
    )
    assert add_r.exit_code == 0, add_r.output
    qid = _task_id_from_output(add_r.output)

    show_r = runner.invoke(app, ["qa", "show", qid], env=env)
    assert show_r.exit_code == 0
    assert "Visual check" in show_r.output

    start_r = runner.invoke(app, ["qa", "start", qid], env=env)
    assert start_r.exit_code == 0
    ls_r = runner.invoke(app, ["qa", "ls", "--wu", wu_id], env=env)
    qid2 = _task_id_from_output(ls_r.output)

    pass_r = runner.invoke(app, ["qa", "pass", qid2, "--evidence", "screen-rec.mp4"], env=env)
    assert pass_r.exit_code == 0


def test_qa_ls_empty(env: dict[str, str], db_url: str) -> None:
    # Use a fresh project so earlier tests' qa rows don't show up.
    empty_project = f"qa-empty-{uuid.uuid4().hex[:6]}"
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO projects (id, name) VALUES (%s, %s)", (empty_project, empty_project)
        )
        conn.commit()
    local_env = {**env, "LUPLO_PROJECT": empty_project}
    r = runner.invoke(app, ["qa", "ls"], env=local_env)
    assert r.exit_code == 0
    assert "No qa_checks" in r.output


def test_qa_fail_path(env: dict[str, str], db_url: str) -> None:
    wu_id = _seed_work_unit(db_url, title="QA fail WU")
    add_r = runner.invoke(
        app,
        [
            "qa",
            "add",
            "Perf budget",
            "--coverage",
            "auto_partial",
            "--wu",
            wu_id,
        ],
        env=env,
    )
    qid = _task_id_from_output(add_r.output)
    runner.invoke(app, ["qa", "start", qid], env=env)
    ls_r = runner.invoke(app, ["qa", "ls", "--wu", wu_id], env=env)
    qid2 = _task_id_from_output(ls_r.output)
    fail_r = runner.invoke(app, ["qa", "fail", qid2, "--reason", "exceeds 16ms"], env=env)
    assert fail_r.exit_code == 0


# ── Check rule pack ─────────────────────────────────────────────


def test_check_list_rules(env: dict[str, str]) -> None:
    r = runner.invoke(app, ["check", "--list"], env=env)
    assert r.exit_code == 0
    assert "missing_rationale" in r.output or "dangling_edge" in r.output


def test_check_run(env: dict[str, str], db_url: str) -> None:
    _seed_item(db_url, title="Decision sans rationale", rationale=None)
    r = runner.invoke(app, ["check", "--severity", "info"], env=env)
    # Some findings may or may not trigger; the command itself should not crash.
    assert r.exit_code in (0, 1)


def test_check_invalid_severity(env: dict[str, str]) -> None:
    r = runner.invoke(app, ["check", "--severity", "nonsense"], env=env)
    assert r.exit_code == 2


def test_check_single_rule(env: dict[str, str]) -> None:
    r = runner.invoke(app, ["check", "--rule", "missing_rationale"], env=env)
    assert r.exit_code in (0, 1)


# ── Impact ──────────────────────────────────────────────────────


def test_impact_no_edges(env: dict[str, str], db_url: str) -> None:
    item_id = _seed_item(db_url, title="Isolated decision")
    r = runner.invoke(app, ["impact", item_id], env=env)
    assert r.exit_code == 0
    assert "Isolated decision" in r.output


def test_impact_json_format(env: dict[str, str], db_url: str) -> None:
    item_id = _seed_item(db_url, title="Json impact root")
    r = runner.invoke(app, ["impact", item_id, "--format", "json"], env=env)
    assert r.exit_code == 0
    assert '"root"' in r.output or "Json impact root" in r.output


def test_impact_flat_format(env: dict[str, str], db_url: str) -> None:
    item_id = _seed_item(db_url, title="Flat impact root")
    r = runner.invoke(app, ["impact", item_id, "--format", "flat"], env=env)
    assert r.exit_code == 0


def test_impact_invalid_format(env: dict[str, str], db_url: str) -> None:
    item_id = _seed_item(db_url, title="Bad format root")
    r = runner.invoke(app, ["impact", item_id, "--format", "xml"], env=env)
    assert r.exit_code == 2


def test_impact_not_found(env: dict[str, str]) -> None:
    r = runner.invoke(app, ["impact", str(uuid.uuid4())], env=env)
    assert r.exit_code != 0


# ── Server config commands ──────────────────────────────────────


def test_server_init_secrets(tmp_path, env: dict[str, str]) -> None:
    out = tmp_path / "cfg.toml"
    r = runner.invoke(app, ["server", "init-secrets", "--output", str(out)], env=env)
    assert r.exit_code == 0
    assert out.exists()
    body = out.read_text()
    assert "jwt" in body.lower() or "secret" in body.lower() or "db_url" in body

    # Second call without --force must refuse.
    r2 = runner.invoke(app, ["server", "init-secrets", "--output", str(out)], env=env)
    assert r2.exit_code == 1

    # --force overwrites.
    r3 = runner.invoke(
        app,
        ["server", "init-secrets", "--output", str(out), "--force"],
        env=env,
    )
    assert r3.exit_code == 0


def test_server_config_check_missing_secret(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LUPLO_JWT_SECRET", raising=False)
    r = runner.invoke(app, ["server", "config-check"], env=env)
    # Missing JWT secret → exit 1 via fail_fast_check.
    assert r.exit_code == 1
    assert "jwt_secret" in r.output.lower() or "missing" in r.output.lower()


def test_server_config_check_ok(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUPLO_JWT_SECRET", "x" * 48)
    r = runner.invoke(app, ["server", "config-check"], env=env)
    assert r.exit_code == 0
    assert "Config OK" in r.output


# ── Admin set-password ──────────────────────────────────────────


def test_admin_set_password_unknown_email(env: dict[str, str]) -> None:
    r = runner.invoke(
        app,
        ["admin", "set-password", "nope@nowhere.com", "-P", "correcthorse123"],
        env=env,
    )
    assert r.exit_code == 1
    assert "not found" in r.output.lower()


def test_admin_set_password_success(env: dict[str, str], db_url: str) -> None:
    aid = str(uuid.uuid4())
    email = f"admin-{aid[:8]}@test.com"
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO actors (id, name, email) VALUES (%s, %s, %s)",
            (aid, "Admin Test", email),
        )
        conn.commit()

    r = runner.invoke(
        app,
        ["admin", "set-password", email, "-P", "correcthorsebattery123"],
        env=env,
    )
    assert r.exit_code == 0, r.output
    assert "updated" in r.output.lower()


# ── Remote auth commands ────────────────────────────────────────


def test_login_no_server(env: dict[str, str]) -> None:
    """No server URL configured → error path."""
    r = runner.invoke(app, ["login", "-e", "x@y.com", "-P", "pw"], env=env)
    assert r.exit_code == 1


def test_logout_no_server(env: dict[str, str]) -> None:
    r = runner.invoke(app, ["logout"], env=env)
    assert r.exit_code == 1


def test_whoami_not_logged_in(env: dict[str, str]) -> None:
    # Provide a --server so the config resolution succeeds.
    r = runner.invoke(app, ["whoami", "--server", "http://nowhere.invalid"], env=env)
    assert r.exit_code == 1
    assert "Not logged in" in r.output


def test_whoami_no_keyring_backend(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    """Headless CI has no keyring backend — must still report 'Not logged in',
    not surface a NoKeyringError stack trace."""
    import keyring
    from keyring.errors import NoKeyringError

    def _raise(*_a: object, **_k: object) -> None:
        raise NoKeyringError("No recommended backend")

    monkeypatch.setattr(keyring, "get_password", _raise)
    r = runner.invoke(app, ["whoami", "--server", "http://nowhere.invalid"], env=env)
    assert r.exit_code == 1
    assert "Not logged in" in r.output


def test_token_refresh_not_logged_in(env: dict[str, str]) -> None:
    r = runner.invoke(app, ["token", "refresh", "--server", "http://nowhere.invalid"], env=env)
    assert r.exit_code == 1


def test_login_with_oauth_flag_errors(env: dict[str, str]) -> None:
    r = runner.invoke(
        app,
        [
            "login",
            "--server",
            "http://nowhere.invalid",
            "--oauth",
            "github",
            "-e",
            "x@y.com",
            "-P",
            "pw",
        ],
        env=env,
    )
    assert r.exit_code == 2
    assert "oauth" in r.output.lower()


# ── Missing config paths (force error branches) ────────────────


def test_items_add_missing_project(db_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    # Strip any leaked shell env + run from a cwd with no .luplo file.
    monkeypatch.delenv("LUPLO_PROJECT", raising=False)
    monkeypatch.delenv("LUPLO_ACTOR_ID", raising=False)
    monkeypatch.chdir(tmp_path)
    bad_env = {"LUPLO_DB_URL": db_url, "LUPLO_ACTOR_ID": _CLI_ACTOR}
    r = runner.invoke(app, ["items", "add", "x"], env=bad_env)
    assert r.exit_code == 1
    assert "project" in r.output.lower()


def test_items_add_missing_actor(db_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("LUPLO_PROJECT", raising=False)
    monkeypatch.delenv("LUPLO_ACTOR_ID", raising=False)
    monkeypatch.chdir(tmp_path)
    bad_env = {"LUPLO_DB_URL": db_url, "LUPLO_PROJECT": _CLI_PROJECT}
    r = runner.invoke(app, ["items", "add", "x"], env=bad_env)
    assert r.exit_code == 1
    assert "actor" in r.output.lower()
