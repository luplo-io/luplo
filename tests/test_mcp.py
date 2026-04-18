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
        "luplo_work_resume",
        "luplo_work_close",
        "luplo_item_upsert",
        "luplo_item_search",
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
    }
    missing = expected - tool_names
    assert not missing, f"Missing MCP tools: {missing}"


def test_mcp_tool_count() -> None:
    tools = mcp._tool_manager.list_tools()
    assert len(tools) == 21


# ── Invocation tests ────────────────────────────────────────────

_MCP_PROJECT = "mcp-test-project"
_MCP_ACTOR = "00000000-0000-0000-0000-0000000000d1"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def mcp_backend(db_url: str) -> Any:
    """Create the MCP backend once per module + close the pool at teardown.

    Environment setup, singleton reset, and seed inserts all happen once so
    every test reuses the same pool. The pool *must* be closed at the end
    of the module so the session-scoped DB fixture can drop the database.
    """
    import os

    os.environ["LUPLO_DB_URL"] = db_url
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
