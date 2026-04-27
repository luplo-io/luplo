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


def test_items_add_and_list_by_work_unit(env: dict[str, str], db_url: str) -> None:
    """`lp items add --wu` attaches the item; `lp items list --wu` filters to it."""
    wu_id = _seed_work_unit(db_url, title="Items WU")
    add_in = runner.invoke(app, ["items", "add", "Inside WU", "--wu", wu_id], env=env)
    assert add_in.exit_code == 0
    add_out = runner.invoke(app, ["items", "add", "Outside WU"], env=env)
    assert add_out.exit_code == 0

    result = runner.invoke(app, ["items", "list", "--wu", wu_id], env=env)
    assert result.exit_code == 0
    assert "Inside WU" in result.output
    assert "Outside WU" not in result.output


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


def test_glossary_group_create_seeds_canonical(env: dict[str, str]) -> None:
    create = runner.invoke(app, ["glossary", "group", "create", "vendor-cli"], env=env)
    assert create.exit_code == 0, create.output
    assert "vendor-cli" in create.output

    listed = runner.invoke(app, ["glossary", "ls"], env=env)
    assert "vendor-cli" in listed.output


def test_glossary_add_alias_then_remove(env: dict[str, str]) -> None:
    create = runner.invoke(app, ["glossary", "group", "create", "shop-cli"], env=env)
    assert create.exit_code == 0
    # Use the visible 8-char prefix from the output as group id.
    gid_match = re.search(r"group \[([0-9a-f]{8})\]", create.output)
    assert gid_match, create.output
    gid = gid_match.group(1)

    add = runner.invoke(app, ["glossary", "add", "store-cli", "--group", gid], env=env)
    assert add.exit_code == 0, add.output
    assert "(alias)" in add.output

    tid_match = re.search(r"\[([0-9a-f]{8})\] \"store-cli\"", add.output)
    assert tid_match, add.output
    tid = tid_match.group(1)

    rm = runner.invoke(app, ["glossary", "term", "rm", tid], env=env)
    assert rm.exit_code == 0, rm.output


def test_glossary_term_rm_canonical_with_alias_blocks(env: dict[str, str]) -> None:
    """Removing a canonical while aliases remain must be refused (ConflictError)."""
    create = runner.invoke(app, ["glossary", "group", "create", "merchant-cli"], env=env)
    gid_match = re.search(r"group \[([0-9a-f]{8})\]", create.output)
    assert gid_match, create.output
    gid = gid_match.group(1)
    canon_term_match = re.search(r"canonical term \[([0-9a-f]{8})\]", create.output)
    assert canon_term_match, create.output
    canonical_tid = canon_term_match.group(1)

    runner.invoke(app, ["glossary", "add", "biz-cli", "--group", gid], env=env)

    blocked = runner.invoke(app, ["glossary", "term", "rm", canonical_tid], env=env)
    assert blocked.exit_code != 0
    combined = (blocked.output or "") + (getattr(blocked, "stderr", "") or "")
    assert "alias" in combined.lower() or "canonical" in combined.lower()


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


def test_work_ls_includes_closed_when_no_filter(env: dict[str, str], db_url: str) -> None:
    """`lp work ls` returns work units regardless of status by default."""
    wu_id = _seed_work_unit(db_url, title="Listable WU")
    runner.invoke(app, ["work", "close", wu_id], env=env)

    result = runner.invoke(app, ["work", "ls"], env=env)
    assert result.exit_code == 0
    assert "Listable WU" in result.output
    assert wu_id[:8] in result.output


def test_work_ls_filters_in_progress(env: dict[str, str], db_url: str) -> None:
    """--status in_progress excludes closed work units."""
    open_wu = _seed_work_unit(db_url, title="Still open")
    closed_wu = _seed_work_unit(db_url, title="Already closed")
    runner.invoke(app, ["work", "close", closed_wu], env=env)

    result = runner.invoke(app, ["work", "ls", "--status", "in_progress"], env=env)
    assert result.exit_code == 0
    assert open_wu[:8] in result.output
    assert closed_wu[:8] not in result.output


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


def test_task_done_after_done_reports_state_transition_error(
    env: dict[str, str], db_url: str
) -> None:
    """A second 'task done' on an already-done task fails cleanly.

    Regression for the bug where TaskStateTransitionError (a ConflictError
    subclass) was not handled by _run and surfaced as a Python traceback.
    """
    wu_id = _seed_work_unit(db_url, title="State machine WU")
    add = runner.invoke(app, ["task", "add", "T", "--wu", wu_id], env=env)
    tid = _task_id_from_output(add.output)
    runner.invoke(app, ["task", "start", tid], env=env)
    runner.invoke(app, ["task", "done", tid], env=env)

    second = runner.invoke(app, ["task", "done", tid], env=env)
    assert second.exit_code != 0
    assert "Traceback" not in second.output
    combined = (second.output or "") + (getattr(second, "stderr", "") or "")
    assert "transition" in combined.lower() or "error" in combined.lower()


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
