"""Tests for core/tasks.py + LocalBackend task wrappers (Phase D)."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from psycopg_pool import AsyncConnectionPool

from luplo.core.backend.local import LocalBackend
from luplo.core.errors import (
    TaskAlreadyInProgressError,
    TaskNotFoundError,
    TaskStateTransitionError,
    WorkUnitHasActiveTasksError,
)


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
async def fresh_wu(backend: LocalBackend):  # type: ignore[no-untyped-def]
    """Returns (project_id, actor_id, work_unit_id) seeded for one test."""
    pid = f"proj-{_uid()[:8]}"
    aid = _uid()
    await backend.create_project(id=pid, name=pid)
    await backend.create_actor(id=aid, name="Tester", email=f"{aid[:8]}@t.com")
    wu = await backend.open_work_unit(
        id=_uid(), project_id=pid, title="Task tests WU", created_by=aid,
    )
    return pid, aid, wu.id


# ── Create / list / sort_order ──────────────────────────────────


@pytest.mark.asyncio
async def test_create_task_default_status(backend: LocalBackend, fresh_wu) -> None:
    pid, aid, wu_id = fresh_wu
    t = await backend.create_task(
        project_id=pid, work_unit_id=wu_id, title="T1", actor_id=aid,
    )
    assert t.context["status"] == "proposed"
    assert t.context["sort_order"] == 10


@pytest.mark.asyncio
async def test_sort_order_gap_strategy(backend: LocalBackend, fresh_wu) -> None:
    pid, aid, wu_id = fresh_wu
    t1 = await backend.create_task(
        project_id=pid, work_unit_id=wu_id, title="T1", actor_id=aid,
    )
    t2 = await backend.create_task(
        project_id=pid, work_unit_id=wu_id, title="T2", actor_id=aid,
    )
    assert t1.context["sort_order"] == 10
    assert t2.context["sort_order"] == 20


@pytest.mark.asyncio
async def test_list_tasks_returns_heads_only(backend: LocalBackend, fresh_wu) -> None:
    pid, aid, wu_id = fresh_wu
    a = await backend.create_task(project_id=pid, work_unit_id=wu_id,
                                  title="A", actor_id=aid)
    b = await backend.create_task(project_id=pid, work_unit_id=wu_id,
                                  title="B", actor_id=aid)
    started = await backend.start_task(a.id, actor_id=aid)
    rows = await backend.list_tasks(wu_id)
    ids = {r.id for r in rows}
    assert started.id in ids
    assert b.id in ids
    assert a.id not in ids  # superseded — not a head


# ── State transitions ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_lifecycle_proposed_to_done(
    backend: LocalBackend, fresh_wu
) -> None:
    pid, aid, wu_id = fresh_wu
    t = await backend.create_task(project_id=pid, work_unit_id=wu_id,
                                  title="L", actor_id=aid)
    started = await backend.start_task(t.id, actor_id=aid)
    assert started.context["status"] == "in_progress"
    done = await backend.complete_task(started.id, actor_id=aid, summary="ok")
    assert done.context["status"] == "done"
    assert done.context["summary"] == "ok"


@pytest.mark.asyncio
async def test_blocked_to_in_progress_to_done(
    backend: LocalBackend, fresh_wu
) -> None:
    pid, aid, wu_id = fresh_wu
    t = await backend.create_task(project_id=pid, work_unit_id=wu_id,
                                  title="X", actor_id=aid)
    blocked = await backend.block_task(t.id, actor_id=aid, reason="waiting")
    assert blocked.context["status"] == "blocked"
    started = await backend.start_task(blocked.id, actor_id=aid)
    assert started.context["status"] == "in_progress"
    # blocked_reason cleared on (re)start
    assert "blocked_reason" not in started.context
    done = await backend.complete_task(started.id, actor_id=aid)
    assert done.context["status"] == "done"


@pytest.mark.asyncio
async def test_done_cannot_restart(
    backend: LocalBackend, fresh_wu
) -> None:
    pid, aid, wu_id = fresh_wu
    t = await backend.create_task(project_id=pid, work_unit_id=wu_id,
                                  title="Z", actor_id=aid)
    started = await backend.start_task(t.id, actor_id=aid)
    done = await backend.complete_task(started.id, actor_id=aid)
    with pytest.raises(TaskStateTransitionError):
        await backend.start_task(done.id, actor_id=aid)


@pytest.mark.asyncio
async def test_two_in_progress_rejected(
    backend: LocalBackend, fresh_wu
) -> None:
    pid, aid, wu_id = fresh_wu
    a = await backend.create_task(project_id=pid, work_unit_id=wu_id,
                                  title="A", actor_id=aid)
    b = await backend.create_task(project_id=pid, work_unit_id=wu_id,
                                  title="B", actor_id=aid)
    await backend.start_task(a.id, actor_id=aid)
    with pytest.raises(TaskAlreadyInProgressError):
        await backend.start_task(b.id, actor_id=aid)


# ── block_task cross-cutting → decision item ───────────────────


@pytest.mark.asyncio
async def test_block_creates_decision_item(
    backend: LocalBackend, fresh_wu
) -> None:
    pid, aid, wu_id = fresh_wu
    t = await backend.create_task(project_id=pid, work_unit_id=wu_id,
                                  title="API down", actor_id=aid)
    blocked = await backend.block_task(
        t.id, actor_id=aid, reason="upstream API returns 500",
    )
    decisions = await backend.list_items(pid, item_type="decision")
    titles = [d.title for d in decisions]
    assert any("Task blocked: API down" in t for t in titles)
    matching = [d for d in decisions if d.title == "Task blocked: API down"]
    assert matching
    d = matching[0]
    assert d.context.get("source") == "task_block"
    assert d.context.get("task_id") == blocked.id
    assert "task_block" in d.tags


# ── reorder (in-place) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_reorder_in_place_no_supersede(
    backend: LocalBackend, fresh_wu
) -> None:
    pid, aid, wu_id = fresh_wu
    a = await backend.create_task(project_id=pid, work_unit_id=wu_id,
                                  title="A", actor_id=aid)
    b = await backend.create_task(project_id=pid, work_unit_id=wu_id,
                                  title="B", actor_id=aid)
    c = await backend.create_task(project_id=pid, work_unit_id=wu_id,
                                  title="C", actor_id=aid)
    refreshed = await backend.reorder_tasks(
        wu_id, [c.id, a.id, b.id], actor_id=aid,
    )
    assert [r.context["sort_order"] for r in refreshed] == [10, 20, 30]
    # IDs must NOT change (in-place per P10)
    assert {r.id for r in refreshed} == {a.id, b.id, c.id}


@pytest.mark.asyncio
async def test_reorder_unknown_id_raises(
    backend: LocalBackend, fresh_wu
) -> None:
    pid, aid, wu_id = fresh_wu
    a = await backend.create_task(project_id=pid, work_unit_id=wu_id,
                                  title="A", actor_id=aid)
    with pytest.raises(TaskNotFoundError):
        await backend.reorder_tasks(
            wu_id, [a.id, _uid()], actor_id=aid,
        )


# ── close_work_unit gate ───────────────────────────────────────


@pytest.mark.asyncio
async def test_close_wu_refused_when_in_progress(
    backend: LocalBackend, fresh_wu
) -> None:
    pid, aid, wu_id = fresh_wu
    t = await backend.create_task(project_id=pid, work_unit_id=wu_id,
                                  title="busy", actor_id=aid)
    await backend.start_task(t.id, actor_id=aid)
    with pytest.raises(WorkUnitHasActiveTasksError):
        await backend.close_work_unit(wu_id, actor_id=aid)


@pytest.mark.asyncio
async def test_close_wu_force_succeeds(
    backend: LocalBackend, fresh_wu
) -> None:
    pid, aid, wu_id = fresh_wu
    t = await backend.create_task(project_id=pid, work_unit_id=wu_id,
                                  title="busy", actor_id=aid)
    await backend.start_task(t.id, actor_id=aid)
    closed = await backend.close_work_unit(wu_id, actor_id=aid, force=True)
    assert closed.status == "done"


@pytest.mark.asyncio
async def test_close_wu_ok_when_no_in_progress(
    backend: LocalBackend, fresh_wu
) -> None:
    pid, aid, wu_id = fresh_wu
    t = await backend.create_task(project_id=pid, work_unit_id=wu_id,
                                  title="OK", actor_id=aid)
    started = await backend.start_task(t.id, actor_id=aid)
    await backend.complete_task(started.id, actor_id=aid)
    closed = await backend.close_work_unit(wu_id, actor_id=aid)
    assert closed.status == "done"


# ── get_in_progress ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_in_progress(
    backend: LocalBackend, fresh_wu
) -> None:
    pid, aid, wu_id = fresh_wu
    assert await backend.get_in_progress_task(wu_id) is None
    t = await backend.create_task(project_id=pid, work_unit_id=wu_id,
                                  title="P", actor_id=aid)
    started = await backend.start_task(t.id, actor_id=aid)
    current = await backend.get_in_progress_task(wu_id)
    assert current is not None
    assert current.id == started.id
