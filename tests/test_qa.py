"""Tests for core/qa.py + LocalBackend qa wrappers + revalidation trigger
(Phases D/E)."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from luplo.core.backend.local import LocalBackend
from luplo.core.errors import QACheckNotFoundError, QAStateTransitionError
from luplo.core.models import ItemCreate


def _uid() -> str:
    return str(uuid.uuid4())


@pytest_asyncio.fixture
async def backend(db_url: str):  # type: ignore[no-untyped-def]
    pool = AsyncConnectionPool(db_url, open=False)
    await pool.open()
    try:
        yield LocalBackend(pool)
    finally:
        await pool.close()


@pytest_asyncio.fixture
async def fresh_ctx(backend: LocalBackend):  # type: ignore[no-untyped-def]
    pid = f"proj-{_uid()[:8]}"
    aid = _uid()
    await backend.create_project(id=pid, name=pid)
    await backend.create_actor(id=aid, name="Tester", email=f"{aid[:8]}@t.com")
    wu = await backend.open_work_unit(
        id=_uid(), project_id=pid, title="QA tests WU", created_by=aid,
    )
    return pid, aid, wu.id


# ── Create / list ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_qa(backend: LocalBackend, fresh_ctx) -> None:
    pid, aid, wu_id = fresh_ctx
    q = await backend.create_qa(
        project_id=pid, title="VFX check", actor_id=aid,
        coverage="human_only", areas=["vfx", "edge_case"],
        work_unit_id=wu_id,
    )
    assert q.context["status"] == "pending"
    assert q.context["coverage"] == "human_only"
    assert q.context["areas"] == ["vfx", "edge_case"]


@pytest.mark.asyncio
async def test_list_qa_filters_by_status(
    backend: LocalBackend, fresh_ctx
) -> None:
    pid, aid, wu_id = fresh_ctx
    q1 = await backend.create_qa(
        project_id=pid, title="A", actor_id=aid, coverage="human_only",
        work_unit_id=wu_id,
    )
    q2 = await backend.create_qa(
        project_id=pid, title="B", actor_id=aid, coverage="auto_partial",
        work_unit_id=wu_id,
    )
    passed = await backend.pass_qa(q1.id, actor_id=aid)
    pending = await backend.list_qa(pid, status="pending")
    pending_ids = {p.id for p in pending}
    assert q2.id in pending_ids
    assert passed.id not in pending_ids


# ── State transitions ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_pass_then_cannot_fail(
    backend: LocalBackend, fresh_ctx
) -> None:
    pid, aid, wu_id = fresh_ctx
    q = await backend.create_qa(project_id=pid, title="x", actor_id=aid,
                                coverage="human_only", work_unit_id=wu_id)
    passed = await backend.pass_qa(q.id, actor_id=aid)
    with pytest.raises(QAStateTransitionError):
        await backend.fail_qa(passed.id, actor_id=aid, reason="late")


@pytest.mark.asyncio
async def test_fail_then_retry(backend: LocalBackend, fresh_ctx) -> None:
    pid, aid, wu_id = fresh_ctx
    q = await backend.create_qa(project_id=pid, title="r", actor_id=aid,
                                coverage="human_only", work_unit_id=wu_id)
    failed = await backend.fail_qa(q.id, actor_id=aid, reason="bad")
    assert failed.context["status"] == "failed"
    started = await backend.start_qa(failed.id, actor_id=aid)
    assert started.context["status"] == "in_progress"


@pytest.mark.asyncio
async def test_assign_qa(backend: LocalBackend, fresh_ctx) -> None:
    pid, aid, wu_id = fresh_ctx
    assignee = _uid()
    await backend.create_actor(
        id=assignee, name="Assignee", email=f"{assignee[:8]}@t.com",
    )
    q = await backend.create_qa(project_id=pid, title="a", actor_id=aid,
                                coverage="human_only", work_unit_id=wu_id)
    assigned = await backend.assign_qa(
        q.id, actor_id=aid, assignee_actor_id=assignee,
    )
    assert assigned.context["assignee"] == assignee


@pytest.mark.asyncio
async def test_get_qa_not_found(backend: LocalBackend) -> None:
    assert await backend.get_qa(_uid()) is None


# ── Target lookups (GIN) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_list_pending_for_task(
    backend: LocalBackend, fresh_ctx
) -> None:
    pid, aid, wu_id = fresh_ctx
    t = await backend.create_task(project_id=pid, work_unit_id=wu_id,
                                  title="T", actor_id=aid)
    q1 = await backend.create_qa(
        project_id=pid, title="q1", actor_id=aid, coverage="human_only",
        target_task_ids=[t.id], work_unit_id=wu_id,
    )
    q2 = await backend.create_qa(
        project_id=pid, title="q2 unrelated", actor_id=aid,
        coverage="auto_partial", work_unit_id=wu_id,
    )
    pending = await backend.list_pending_qa_for_task(t.id)
    ids = {p.id for p in pending}
    assert q1.id in ids
    assert q2.id not in ids


@pytest.mark.asyncio
async def test_list_pending_for_item(
    backend: LocalBackend, fresh_ctx
) -> None:
    pid, aid, wu_id = fresh_ctx
    target = await backend.create_item(
        ItemCreate(project_id=pid, actor_id=aid, item_type="knowledge",
                   title="target")
    )
    q = await backend.create_qa(
        project_id=pid, title="q", actor_id=aid, coverage="human_only",
        target_item_ids=[target.id], work_unit_id=wu_id,
    )
    pending = await backend.list_pending_qa_for_item(target.id)
    assert q.id in {p.id for p in pending}


# ── Revalidation trigger (P8 — in-place + audit) ───────────────


@pytest.mark.asyncio
async def test_supersede_revalidates_passed_qa(
    backend: LocalBackend, fresh_ctx
) -> None:
    pid, aid, wu_id = fresh_ctx
    target = await backend.create_item(
        ItemCreate(project_id=pid, actor_id=aid, item_type="knowledge",
                   title="design v1", body="...")
    )
    q = await backend.create_qa(
        project_id=pid, title="check", actor_id=aid, coverage="human_only",
        target_item_ids=[target.id], work_unit_id=wu_id,
    )
    passed = await backend.pass_qa(q.id, actor_id=aid)
    assert passed.context["status"] == "passed"

    # Supersede the target item.
    new_target = await backend.create_item(
        ItemCreate(project_id=pid, actor_id=aid, item_type="knowledge",
                   title="design v2", body="updated",
                   supersedes_id=target.id)
    )

    # qa_check should now be back to 'pending' (in-place; same id).
    refreshed = await backend.get_qa(passed.id)
    assert refreshed is not None
    assert refreshed.id == passed.id  # in-place — id unchanged
    assert refreshed.context["status"] == "pending"

    # Audit log should include a revalidation entry.
    async with backend._pool.connection() as conn:  # type: ignore[attr-defined]
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT metadata FROM audit_log"
                " WHERE target_id = %s AND action = 'item.update'"
                " ORDER BY id DESC LIMIT 1",
                (passed.id,),
            )
            row = await cur.fetchone()
    assert row is not None
    md = row["metadata"]
    assert md.get("trigger") == "supersede_revalidation"
    assert md.get("status_transition") == "passed→pending"
    assert md.get("source_item_id") == new_target.id


@pytest.mark.asyncio
async def test_supersede_does_not_revalidate_unrelated_qa(
    backend: LocalBackend, fresh_ctx
) -> None:
    pid, aid, wu_id = fresh_ctx
    target = await backend.create_item(
        ItemCreate(project_id=pid, actor_id=aid, item_type="knowledge",
                   title="target", body="...")
    )
    other = await backend.create_item(
        ItemCreate(project_id=pid, actor_id=aid, item_type="knowledge",
                   title="other", body="...")
    )
    q = await backend.create_qa(
        project_id=pid, title="check", actor_id=aid, coverage="human_only",
        target_item_ids=[target.id], work_unit_id=wu_id,
    )
    passed = await backend.pass_qa(q.id, actor_id=aid)
    # Supersede an UNRELATED item.
    await backend.create_item(
        ItemCreate(project_id=pid, actor_id=aid, item_type="knowledge",
                   title="other v2", supersedes_id=other.id)
    )
    still = await backend.get_qa(passed.id)
    assert still is not None
    assert still.context["status"] == "passed"  # untouched
