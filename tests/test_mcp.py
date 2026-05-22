"""Smoke + invocation tests for the MCP server.

Tool registration smoke tests live alongside end-to-end tool calls that
exercise the handler bodies. Each test resets the module-level backend
singleton so the backend is re-created against the session DB url.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import psycopg
import pytest
import pytest_asyncio

import luplo.mcp as mcp_mod
from luplo.mcp import mcp


def test_mcp_server_has_name() -> None:
    assert mcp.name == "luplo"


def test_mcp_tools_registered() -> None:
    tool_names = {t.name for t in mcp._tool_manager.list_tools()}
    expected = {
        "luplo_work_open",
        "luplo_work_list",
        "luplo_work_resume",
        "luplo_work_close",
        "luplo_item_upsert",
        "luplo_item_search",
        "luplo_item_show",
        "luplo_impact",
        "luplo_brief",
        "luplo_page_sync",
        "luplo_history_query",
        "luplo_save_decisions",
        "luplo_task_add",
        "luplo_task_list",
        "luplo_task_start",
        "luplo_task_done",
        "luplo_task_block",
        "luplo_task_edit",
        "luplo_check",
        "luplo_qa_add",
        "luplo_qa_pass",
        "luplo_qa_fail",
        "luplo_qa_list_pending",
        "luplo_idea_add",
        "luplo_idea_list",
        "luplo_idea_search",
        "luplo_idea_redact",
        "luplo_capture_add",
        "luplo_capture_list",
        "luplo_capture_search",
        "luplo_capture_set_state",
        "luplo_capture_discard",
        "luplo_capture_redact",
        "luplo_capture_annotate",
        "luplo_capture_promote",
    }
    missing = expected - tool_names
    assert not missing, f"Missing MCP tools: {missing}"


def test_mcp_tool_count() -> None:
    tools = mcp._tool_manager.list_tools()
    assert len(tools) == 37


# ── Invocation tests ────────────────────────────────────────────

_MCP_PROJECT = "mcp-test-project"
_MCP_ACTOR = "00000000-0000-0000-0000-0000000000d1"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def mcp_backend(db_url: str) -> Any:
    """Create the MCP backend once per module + close the pool at teardown.

    Environment setup, singleton reset, and seed inserts all happen once so
    every test reuses the same pool. The pool *must* be closed at the end
    of the module so the session-scoped DB fixture can drop the database.

    A hermetic ``load_config`` is patched in: without this the test picks
    up the developer's ``.luplo`` from the working tree, which on this
    machine is in remote mode and would route ``_get_backend`` at the
    cloud (failing with ``_RemoteAuthMissing``).
    """
    import os

    from luplo.config import LuploConfig

    os.environ["LUPLO_DB_URL"] = db_url
    _orig_load_config = mcp_mod.load_config
    mcp_mod.load_config = lambda: LuploConfig()
    mcp_mod._backend = None

    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO projects (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (_MCP_PROJECT, "MCP Test"),
        )
        conn.execute(
            "INSERT INTO actors (id, name, email) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (_MCP_ACTOR, "MCP Actor", "mcp@test.com"),
        )
        conn.commit()

    backend = await mcp_mod._get_backend()
    try:
        yield backend
    finally:
        if mcp_mod._backend is not None:
            await mcp_mod._backend.pool.close()
            mcp_mod._backend = None
        mcp_mod.load_config = _orig_load_config


def _wu_id_from_text(text: str) -> str:
    import re

    m = re.search(r"id:\s*([0-9a-f-]{36})", text)
    assert m, f"no work unit id in: {text!r}"
    return m.group(1)


def _item_id_from_text(text: str) -> str:
    import re

    m = re.search(r"id:\s*([0-9a-f-]{36})", text)
    assert m, f"no item id in: {text!r}"
    return m.group(1)


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_work_open_and_close(mcp_backend: Any) -> None:
    out = await mcp_mod.luplo_work_open(
        title="MCP sprint",
        project_id=_MCP_PROJECT,
        description="test",
        actor_id=_MCP_ACTOR,
    )
    assert "Opened" in out
    wu_id = _wu_id_from_text(out)
    closed = await mcp_mod.luplo_work_close(work_unit_id=wu_id, actor_id=_MCP_ACTOR)
    assert "Closed" in closed


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_work_list_filters_by_status(mcp_backend: Any) -> None:
    open_out = await mcp_mod.luplo_work_open(
        title="Listable MCP",
        project_id=_MCP_PROJECT,
        actor_id=_MCP_ACTOR,
    )
    wu_id = _wu_id_from_text(open_out)

    listed = await mcp_mod.luplo_work_list(project_id=_MCP_PROJECT, status="in_progress")
    assert wu_id[:8] in listed

    await mcp_mod.luplo_work_close(work_unit_id=wu_id, actor_id=_MCP_ACTOR)

    after_close = await mcp_mod.luplo_work_list(project_id=_MCP_PROJECT, status="in_progress")
    assert wu_id[:8] not in after_close

    all_status = await mcp_mod.luplo_work_list(project_id=_MCP_PROJECT)
    assert wu_id[:8] in all_status


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_work_close_unknown(mcp_backend: Any) -> None:
    out = await mcp_mod.luplo_work_close(work_unit_id=str(uuid.uuid4()), actor_id=_MCP_ACTOR)
    assert "not found" in out.lower() or "already" in out.lower()


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_work_resume_no_match(mcp_backend: Any) -> None:
    out = await mcp_mod.luplo_work_resume(
        query=f"nope-{uuid.uuid4().hex[:6]}", project_id=_MCP_PROJECT
    )
    assert "No matching" in out


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_work_resume_with_tasks(mcp_backend: Any) -> None:
    open_out = await mcp_mod.luplo_work_open(
        title="Resumable MCP",
        project_id=_MCP_PROJECT,
        actor_id=_MCP_ACTOR,
    )
    wu_id = _wu_id_from_text(open_out)
    await mcp_mod.luplo_task_add(
        title="First MCP task",
        project_id=_MCP_PROJECT,
        work_unit_id=wu_id,
        actor_id=_MCP_ACTOR,
    )
    out = await mcp_mod.luplo_work_resume(query="Resumable", project_id=_MCP_PROJECT)
    assert "Resumable MCP" in out
    assert "First MCP task" in out


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_item_upsert_and_search(mcp_backend: Any) -> None:
    add = await mcp_mod.luplo_item_upsert(
        title="MCP vendor rule",
        project_id=_MCP_PROJECT,
        item_type="decision",
        body="shops restock at dawn",
        rationale="consistency",
        actor_id=_MCP_ACTOR,
    )
    assert "Created" in add

    results = await mcp_mod.luplo_item_search(query="vendor", project_id=_MCP_PROJECT, limit=5)
    assert "MCP vendor rule" in results
    # Search output must expose the item id explicitly so the LLM can chain
    # into luplo_item_show without guessing how to address the result.
    assert "(id: " in results
    assert "luplo_item_show" in results


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_item_show_full_body(mcp_backend: Any) -> None:
    """`luplo_item_show` must return the whole body + rationale, never truncated.

    The preview from `luplo_item_search` caps body at 150 chars; the point of
    this tool is to bypass that cap. A 400-char body lets us assert that
    neither the 150-char nor the 200-char cutoff was silently applied.
    """
    long_body = "x" * 400
    long_rationale = "y" * 400
    add = await mcp_mod.luplo_item_upsert(
        title="MCP show target",
        project_id=_MCP_PROJECT,
        item_type="decision",
        body=long_body,
        rationale=long_rationale,
        actor_id=_MCP_ACTOR,
    )
    # `luplo_item_upsert` returns "Created <type>: <title> (id: <uuid>)"
    item_id = add.rsplit("id: ", 1)[1].rstrip(")").strip()

    shown = await mcp_mod.luplo_item_show(item_id=item_id, project_id=_MCP_PROJECT)
    assert "# MCP show target" in shown
    assert f"- id: {item_id}" in shown
    assert "- type: decision" in shown
    assert "## Body" in shown
    assert long_body in shown
    assert "## Rationale" in shown
    assert long_rationale in shown


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_item_show_not_found(mcp_backend: Any) -> None:
    missing = "deadbeefdeadbeefdeadbeefdeadbeef"
    out = await mcp_mod.luplo_item_show(item_id=missing, project_id=_MCP_PROJECT)
    assert "not found" in out
    assert _MCP_PROJECT in out


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_item_upsert_research_defaults_expiry(mcp_backend: Any) -> None:
    """Research items carry TTL; clean up after the test so alembic downgrade
    in ``test_migration`` can still drop the ``research`` item_type row."""
    out = await mcp_mod.luplo_item_upsert(
        title="MCP research",
        project_id=_MCP_PROJECT,
        item_type="research",
        source_url="https://example.com/a",
        actor_id=_MCP_ACTOR,
    )
    assert "Created" in out
    # Hard-delete (not soft) so the FK from items.item_type -> item_types.key
    # doesn't block the migration downgrade test that runs later.
    async with mcp_mod._backend.pool.connection() as conn:  # type: ignore[union-attr]
        await conn.execute(
            "DELETE FROM items WHERE project_id = %s AND item_type = 'research'",
            (_MCP_PROJECT,),
        )


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_item_upsert_with_explicit_expiry(mcp_backend: Any) -> None:
    out = await mcp_mod.luplo_item_upsert(
        title="MCP explicit expiry",
        project_id=_MCP_PROJECT,
        item_type="knowledge",
        expires_at=datetime(2099, 1, 1).isoformat(),
        actor_id=_MCP_ACTOR,
    )
    assert "Created" in out


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_item_search_empty(mcp_backend: Any) -> None:
    unique = f"zzzz{uuid.uuid4().hex[:8]}zzzz"
    out = await mcp_mod.luplo_item_search(query=unique, project_id=_MCP_PROJECT)
    assert "No results" in out


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_brief_and_keyword(mcp_backend: Any) -> None:
    brief = await mcp_mod.luplo_brief(project_id=_MCP_PROJECT)
    assert "Active Work Units" in brief or "No active" in brief

    # Brief with keyword uses search path.
    brief_kw = await mcp_mod.luplo_brief(project_id=_MCP_PROJECT, keyword="vendor")
    assert "matching" in brief_kw or "No items" in brief_kw


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_task_lifecycle(mcp_backend: Any) -> None:
    open_out = await mcp_mod.luplo_work_open(
        title="MCP lifecycle WU", project_id=_MCP_PROJECT, actor_id=_MCP_ACTOR
    )
    wu_id = _wu_id_from_text(open_out)

    add = await mcp_mod.luplo_task_add(
        title="Do thing",
        project_id=_MCP_PROJECT,
        work_unit_id=wu_id,
        body="detail",
        actor_id=_MCP_ACTOR,
    )
    assert "Created task" in add
    task_id = _item_id_from_text(add)

    listing = await mcp_mod.luplo_task_list(work_unit_id=wu_id)
    assert "Do thing" in listing

    started = await mcp_mod.luplo_task_start(
        task_id=task_id, actor_id=_MCP_ACTOR, project_id=_MCP_PROJECT
    )
    assert "Started" in started
    new_id = _item_id_from_text(started)

    edited = await mcp_mod.luplo_task_edit(
        task_id=new_id,
        title="Do thing better",
        actor_id=_MCP_ACTOR,
        project_id=_MCP_PROJECT,
    )
    assert "Edited" in edited
    edited_id = _item_id_from_text(edited)

    done = await mcp_mod.luplo_task_done(
        task_id=edited_id,
        summary="shipped",
        propose_decision=True,
        actor_id=_MCP_ACTOR,
        project_id=_MCP_PROJECT,
    )
    assert "Completed" in done


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_task_start_collision(mcp_backend: Any) -> None:
    open_out = await mcp_mod.luplo_work_open(
        title="MCP collide WU", project_id=_MCP_PROJECT, actor_id=_MCP_ACTOR
    )
    wu_id = _wu_id_from_text(open_out)

    a = await mcp_mod.luplo_task_add(
        title="A", project_id=_MCP_PROJECT, work_unit_id=wu_id, actor_id=_MCP_ACTOR
    )
    tid_a = _item_id_from_text(a)
    await mcp_mod.luplo_task_start(task_id=tid_a, actor_id=_MCP_ACTOR, project_id=_MCP_PROJECT)

    b = await mcp_mod.luplo_task_add(
        title="B", project_id=_MCP_PROJECT, work_unit_id=wu_id, actor_id=_MCP_ACTOR
    )
    tid_b = _item_id_from_text(b)
    collided = await mcp_mod.luplo_task_start(
        task_id=tid_b, actor_id=_MCP_ACTOR, project_id=_MCP_PROJECT
    )
    assert "Error" in collided


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_task_start_not_found(mcp_backend: Any) -> None:
    out = await mcp_mod.luplo_task_start(
        task_id=str(uuid.uuid4()),
        actor_id=_MCP_ACTOR,
        project_id=_MCP_PROJECT,
    )
    assert "Error" in out


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_task_block(mcp_backend: Any) -> None:
    open_out = await mcp_mod.luplo_work_open(
        title="MCP block WU", project_id=_MCP_PROJECT, actor_id=_MCP_ACTOR
    )
    wu_id = _wu_id_from_text(open_out)
    add = await mcp_mod.luplo_task_add(
        title="Block me",
        project_id=_MCP_PROJECT,
        work_unit_id=wu_id,
        actor_id=_MCP_ACTOR,
    )
    tid = _item_id_from_text(add)
    blocked = await mcp_mod.luplo_task_block(
        task_id=tid,
        reason="waiting on upstream",
        actor_id=_MCP_ACTOR,
        project_id=_MCP_PROJECT,
    )
    assert "Blocked" in blocked


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_task_list_empty(mcp_backend: Any) -> None:
    open_out = await mcp_mod.luplo_work_open(
        title="MCP empty WU", project_id=_MCP_PROJECT, actor_id=_MCP_ACTOR
    )
    wu_id = _wu_id_from_text(open_out)
    out = await mcp_mod.luplo_task_list(work_unit_id=wu_id)
    assert "No tasks" in out


# ── QA ──────────────────────────────────────────────────────────


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_qa_add_pass(mcp_backend: Any) -> None:
    open_out = await mcp_mod.luplo_work_open(
        title="MCP qa WU", project_id=_MCP_PROJECT, actor_id=_MCP_ACTOR
    )
    wu_id = _wu_id_from_text(open_out)
    add = await mcp_mod.luplo_qa_add(
        title="Visual QA",
        project_id=_MCP_PROJECT,
        coverage="human_only",
        areas=["ux"],
        work_unit_id=wu_id,
        actor_id=_MCP_ACTOR,
    )
    assert "Created qa_check" in add
    qid = _item_id_from_text(add)
    passed = await mcp_mod.luplo_qa_pass(
        qa_id=qid, evidence="screen-rec", actor_id=_MCP_ACTOR, project_id=_MCP_PROJECT
    )
    assert "Passed" in passed


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_qa_add_fail(mcp_backend: Any) -> None:
    open_out = await mcp_mod.luplo_work_open(
        title="MCP qa fail WU", project_id=_MCP_PROJECT, actor_id=_MCP_ACTOR
    )
    wu_id = _wu_id_from_text(open_out)
    add = await mcp_mod.luplo_qa_add(
        title="Perf QA",
        project_id=_MCP_PROJECT,
        coverage="auto_partial",
        work_unit_id=wu_id,
        actor_id=_MCP_ACTOR,
    )
    qid = _item_id_from_text(add)
    failed = await mcp_mod.luplo_qa_fail(
        qa_id=qid,
        reason="budget exceeded",
        actor_id=_MCP_ACTOR,
        project_id=_MCP_PROJECT,
    )
    assert "Failed" in failed


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_qa_list_pending(mcp_backend: Any) -> None:
    # The project may have any number of pending qa; just ensure the call
    # returns either a listing or the empty-state string.
    out = await mcp_mod.luplo_qa_list_pending(project_id=_MCP_PROJECT)
    assert "qa_check" in out or "No pending" in out


# ── Check / Impact ──────────────────────────────────────────────


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_check(mcp_backend: Any) -> None:
    out = await mcp_mod.luplo_check(project_id=_MCP_PROJECT, severity="info")
    assert "finding" in out.lower() or "No findings" in out


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_check_invalid_severity(mcp_backend: Any) -> None:
    out = await mcp_mod.luplo_check(project_id=_MCP_PROJECT, severity="catastrophic")
    assert "Error" in out


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_check_single_rule(mcp_backend: Any) -> None:
    out = await mcp_mod.luplo_check(
        project_id=_MCP_PROJECT, rule="missing_rationale", severity="info"
    )
    assert "finding" in out.lower() or "No findings" in out


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_impact_not_found(mcp_backend: Any) -> None:
    out = await mcp_mod.luplo_impact(item_id=str(uuid.uuid4()), project_id=_MCP_PROJECT)
    assert "Error" in out


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_impact_root_only(mcp_backend: Any) -> None:
    # Seed an item directly.
    async with mcp_mod._backend.pool.connection() as conn:  # type: ignore[union-attr]
        item_id = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO items (id, project_id, item_type, title, actor_id, search_tsv) "
            "VALUES (%s, %s, 'decision', %s, %s, to_tsvector('simple', %s))",
            (item_id, _MCP_PROJECT, "Impact root", _MCP_ACTOR, "Impact root"),
        )
    out = await mcp_mod.luplo_impact(item_id=item_id, project_id=_MCP_PROJECT)
    assert "Impact root" in out


# ── History / Sync / Save-decisions ────────────────────────────


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_page_sync(mcp_backend: Any) -> None:
    out = await mcp_mod.luplo_page_sync(
        source_type="notion",
        source_page_id=f"page-{uuid.uuid4().hex[:6]}",
        full_content="# hello",
        project_id=_MCP_PROJECT,
    )
    assert "queued" in out.lower()


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_history_query_empty(mcp_backend: Any) -> None:
    out = await mcp_mod.luplo_history_query(
        project_id=_MCP_PROJECT,
        since=datetime(2099, 1, 1).isoformat(),
        limit=5,
    )
    assert "No history" in out


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_save_decisions_stub(mcp_backend: Any) -> None:
    # Extractor returns an empty list in v0.5; the handler returns the stub string.
    out = await mcp_mod.luplo_save_decisions(
        transcript="we decided to move on",
        project_id=_MCP_PROJECT,
        actor_id=_MCP_ACTOR,
    )
    assert "extraction" in out.lower() or "saved" in out.lower()


# ── _resolve_actor sentinel path ───────────────────────────────


def test_resolve_actor_explicit() -> None:
    assert mcp_mod._resolve_actor("abc") == "abc"


def test_resolve_actor_sentinel_with_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from luplo.config import LuploConfig

    fake = LuploConfig(actor_id="from-config-id")
    monkeypatch.setattr(mcp_mod, "load_config", lambda: fake)
    assert mcp_mod._resolve_actor("claude") == "from-config-id"


def test_resolve_actor_sentinel_without_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from luplo.config import LuploConfig

    monkeypatch.setattr(mcp_mod, "load_config", lambda: LuploConfig())
    with pytest.raises(ValueError):
        mcp_mod._resolve_actor("claude")


# ── Ideas (luplo_idea_add / list / search / redact) ─────────────


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_idea_add_and_list(mcp_backend: Any) -> None:
    open_out = await mcp_mod.luplo_work_open(
        title="MCP idea WU",
        project_id=_MCP_PROJECT,
        actor_id=_MCP_ACTOR,
    )
    wu_id = _wu_id_from_text(open_out)

    added = await mcp_mod.luplo_idea_add(
        text="refresh token rotation thought",
        project_id=_MCP_PROJECT,
        work_unit_id=wu_id,
        actor_id=_MCP_ACTOR,
    )
    assert "Added idea" in added

    listed = await mcp_mod.luplo_idea_list(work_unit_id=wu_id, project_id=_MCP_PROJECT)
    assert "refresh token rotation" in listed


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_capture_add_and_list(mcp_backend: Any) -> None:
    added = await mcp_mod.luplo_capture_add(
        text="mcp raw note",
        actor_id=_MCP_ACTOR,
    )
    assert "Saved capture" in added

    listed = await mcp_mod.luplo_capture_list(limit=10)
    assert "mcp raw note" in listed


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_capture_search_state_discard_and_redact(mcp_backend: Any) -> None:
    import re

    added = await mcp_mod.luplo_capture_add("mcp secret target", actor_id=_MCP_ACTOR)
    match = re.search(r"Saved capture: ([0-9a-f]{8})", added)
    assert match, added
    capture_id = match.group(1)

    found = await mcp_mod.luplo_capture_search(query="mcp secret")
    assert "mcp secret target" in found

    changed = await mcp_mod.luplo_capture_set_state(
        capture_id=capture_id,
        review_state="backlog",
        actor_id=_MCP_ACTOR,
    )
    assert "backlog" in changed

    discarded = await mcp_mod.luplo_capture_discard(capture_id, actor_id=_MCP_ACTOR)
    assert "discarded" in discarded

    hidden = await mcp_mod.luplo_capture_search(query="mcp secret")
    assert "mcp secret target" not in hidden

    redacted = await mcp_mod.luplo_capture_redact(capture_id, actor_id=_MCP_ACTOR)
    assert "redacted" in redacted

    listed = await mcp_mod.luplo_capture_list(include_redacted=True)
    assert "mcp secret target" not in listed
    assert "[redacted]" in listed

    after_redact = await mcp_mod.luplo_capture_search(
        query="mcp secret target",
        include_redacted=True,
    )
    assert "mcp secret target" not in after_redact
    assert "No captures matched." in after_redact


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_capture_annotate(mcp_backend: Any) -> None:
    import re

    added = await mcp_mod.luplo_capture_add("mcp annotation target", actor_id=_MCP_ACTOR)
    match = re.search(r"Saved capture: ([0-9a-f]{8})", added)
    assert match, added
    capture_id = match.group(1)

    result = await mcp_mod.luplo_capture_annotate(
        capture_id=capture_id,
        summary="mcp summary text",
        sensitivity_hint="possible",
        signals={"tags": ["mcp"]},
    )
    assert "Annotated capture" in result

    found = await mcp_mod.luplo_capture_search(query="mcp summary text")
    assert "mcp annotation target" in found


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_capture_promote(mcp_backend: Any) -> None:
    import re

    added = await mcp_mod.luplo_capture_add("mcp promote me", actor_id=_MCP_ACTOR)
    match = re.search(r"Saved capture: ([0-9a-f]{8})", added)
    assert match, added
    capture_id = match.group(1)

    result = await mcp_mod.luplo_capture_promote(
        capture_id=capture_id,
        project_id=_MCP_PROJECT,
        item_type="knowledge",
        title="MCP promoted capture",
        actor_id=_MCP_ACTOR,
    )
    assert "Promoted capture" in result
    assert "MCP promoted capture" in result

    found = await mcp_mod.luplo_item_search(query="MCP promoted", project_id=_MCP_PROJECT)
    assert "MCP promoted capture" in found

    promoted = await mcp_mod.luplo_capture_list(review_state="promoted")
    assert "mcp promote me" in promoted


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_idea_add_rejects_empty_text(mcp_backend: Any) -> None:
    open_out = await mcp_mod.luplo_work_open(
        title="empty-text WU",
        project_id=_MCP_PROJECT,
        actor_id=_MCP_ACTOR,
    )
    wu_id = _wu_id_from_text(open_out)
    out = await mcp_mod.luplo_idea_add(
        text="   ",
        project_id=_MCP_PROJECT,
        work_unit_id=wu_id,
        actor_id=_MCP_ACTOR,
    )
    # Domain ValidationError must surface as a clean "Error: ..." string,
    # not a raw traceback (round-2 threat finding).
    assert out.startswith("Error:")
    assert "empty" in out.lower()


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_idea_list_requires_project_id(mcp_backend: Any) -> None:
    """Round 2 R1: empty project_id must be rejected, not silently global."""
    out = await mcp_mod.luplo_idea_list(work_unit_id=str(uuid.uuid4()), project_id="")
    assert out.startswith("Error:")
    assert "project_id" in out


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_idea_redact_requires_project_id(mcp_backend: Any) -> None:
    """Round 2 R1: redact also rejects empty project_id (no cross-project mutation)."""
    out = await mcp_mod.luplo_idea_redact(idea_id=str(uuid.uuid4()), project_id="")
    assert out.startswith("Error:")
    assert "project_id" in out


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_idea_redact_idempotent(mcp_backend: Any) -> None:
    open_out = await mcp_mod.luplo_work_open(
        title="redact WU",
        project_id=_MCP_PROJECT,
        actor_id=_MCP_ACTOR,
    )
    wu_id = _wu_id_from_text(open_out)
    added = await mcp_mod.luplo_idea_add(
        text="thought to redact",
        project_id=_MCP_PROJECT,
        work_unit_id=wu_id,
        actor_id=_MCP_ACTOR,
    )
    # "Added idea: <id8> (work_unit: <wu8>)" — pull id8
    import re

    m = re.search(r"Added idea: ([0-9a-f]{8})", added)
    assert m, added
    idea_short = m.group(1)

    first = await mcp_mod.luplo_idea_redact(
        idea_id=idea_short,
        project_id=_MCP_PROJECT,
        actor_id=_MCP_ACTOR,
    )
    assert first.startswith("Redacted ")
    second = await mcp_mod.luplo_idea_redact(
        idea_id=idea_short,
        project_id=_MCP_PROJECT,
        actor_id=_MCP_ACTOR,
    )
    assert second.startswith("Already redacted ")


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_idea_redact_unknown_id_clean_error(mcp_backend: Any) -> None:
    """Round 2 threat finding: NotFoundError must surface as clean error, not raw."""
    out = await mcp_mod.luplo_idea_redact(
        idea_id=str(uuid.uuid4()),
        project_id=_MCP_PROJECT,
        actor_id=_MCP_ACTOR,
    )
    assert out.startswith("Error:")
    assert "not found" in out.lower()


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_idea_search_filter_only_and_include_redacted(mcp_backend: Any) -> None:
    open_out = await mcp_mod.luplo_work_open(
        title="search WU",
        project_id=_MCP_PROJECT,
        actor_id=_MCP_ACTOR,
    )
    wu_id = _wu_id_from_text(open_out)
    await mcp_mod.luplo_idea_add(
        text="visible search target",
        project_id=_MCP_PROJECT,
        work_unit_id=wu_id,
        actor_id=_MCP_ACTOR,
    )
    # Filter-only mode (no query) — proves the tool path runs without
    # the FTS predicate.
    out = await mcp_mod.luplo_idea_search(
        project_id=_MCP_PROJECT,
        work_unit_id=wu_id,
    )
    assert "visible search target" in out


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_idea_search_blocks_keyword_oracle(mcp_backend: Any) -> None:
    """Round 2 R3: include_redacted=True with a text query is rejected."""
    out = await mcp_mod.luplo_idea_search(
        project_id=_MCP_PROJECT,
        query="anything",
        include_redacted=True,
    )
    assert out.startswith("Error:")
    assert "oracle" in out.lower()


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_idea_search_garbage_since_helpful_error(mcp_backend: Any) -> None:
    """parse_since errors get caught and surfaced as Error: ..."""
    out = await mcp_mod.luplo_idea_search(
        project_id=_MCP_PROJECT,
        since="yesterday",
    )
    assert out.startswith("Error:")


@pytest.mark.asyncio(loop_scope="module")
async def test_mcp_idea_search_until_anchor_rejected(mcp_backend: Any) -> None:
    """Round 2 B3: anchors are since-only; until=this_month must error."""
    out = await mcp_mod.luplo_idea_search(
        project_id=_MCP_PROJECT,
        until="this_month",
    )
    assert out.startswith("Error:")
    assert "since-only" in out
