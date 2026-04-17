"""Tests for core.tasks.edit_task and its surfaces."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from luplo.core.errors import TaskNotFoundError
from luplo.core.tasks import complete_task, create_task, edit_task, start_task


async def _wu(conn: Any, project_id: str, actor_id: str, title: str = "WU") -> str:
    wu_id = str(uuid.uuid4())
    await conn.execute(
        "INSERT INTO work_units (id, project_id, title, created_by, status)"
        " VALUES (%s, %s, %s, %s, 'in_progress')",
        (wu_id, project_id, title, actor_id),
    )
    return wu_id


@pytest.mark.asyncio
async def test_edit_task_updates_title(conn: Any, seed_project: str, seed_actor: str) -> None:
    wu = await _wu(conn, seed_project, seed_actor)
    original = await create_task(
        conn,
        project_id=seed_project,
        work_unit_id=wu,
        title="Original title",
        actor_id=seed_actor,
    )

    new = await edit_task(conn, original.id, actor_id=seed_actor, title="New title")

    assert new.title == "New title"
    assert new.supersedes_id == original.id
    assert new.id != original.id


@pytest.mark.asyncio
async def test_edit_task_preserves_status(conn: Any, seed_project: str, seed_actor: str) -> None:
    """Editing must NOT change status. A task in_progress stays in_progress."""
    wu = await _wu(conn, seed_project, seed_actor)
    t = await create_task(
        conn, project_id=seed_project, work_unit_id=wu, title="T", actor_id=seed_actor
    )
    started = await start_task(conn, t.id, actor_id=seed_actor)
    assert started.context["status"] == "in_progress"

    edited = await edit_task(conn, started.id, actor_id=seed_actor, body="new body")

    assert edited.context["status"] == "in_progress"
    assert edited.body == "new body"


@pytest.mark.asyncio
async def test_edit_task_preserves_fields_when_not_passed(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    wu = await _wu(conn, seed_project, seed_actor)
    t = await create_task(
        conn,
        project_id=seed_project,
        work_unit_id=wu,
        title="Keep title",
        body="Keep body",
        actor_id=seed_actor,
    )

    edited = await edit_task(conn, t.id, actor_id=seed_actor, sort_order=99)

    assert edited.title == "Keep title"
    assert edited.body == "Keep body"
    assert edited.context["sort_order"] == 99


@pytest.mark.asyncio
async def test_edit_task_no_fields_returns_head_unchanged(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    wu = await _wu(conn, seed_project, seed_actor)
    t = await create_task(
        conn, project_id=seed_project, work_unit_id=wu, title="T", actor_id=seed_actor
    )

    returned = await edit_task(conn, t.id, actor_id=seed_actor)

    assert returned.id == t.id
    assert returned.supersedes_id is None


@pytest.mark.asyncio
async def test_edit_task_walks_supersede_chain(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    """Editing by an older ID in the chain still resolves to the current head."""
    wu = await _wu(conn, seed_project, seed_actor)
    t = await create_task(
        conn, project_id=seed_project, work_unit_id=wu, title="A", actor_id=seed_actor
    )
    v2 = await edit_task(conn, t.id, actor_id=seed_actor, title="B")
    v3 = await edit_task(conn, t.id, actor_id=seed_actor, title="C")

    assert v3.title == "C"
    assert v3.supersedes_id == v2.id


@pytest.mark.asyncio
async def test_edit_task_unknown_id_raises(conn: Any, seed_project: str, seed_actor: str) -> None:
    with pytest.raises(TaskNotFoundError):
        await edit_task(
            conn,
            "99999999-9999-9999-9999-999999999999",
            actor_id=seed_actor,
            title="never",
        )


@pytest.mark.asyncio
async def test_edit_done_task_still_allowed(conn: Any, seed_project: str, seed_actor: str) -> None:
    """A done task is terminal for status transitions, but users must still
    be able to fix a typo in the title after the fact. Edit is status-agnostic."""
    wu = await _wu(conn, seed_project, seed_actor)
    t = await create_task(
        conn, project_id=seed_project, work_unit_id=wu, title="Old", actor_id=seed_actor
    )
    started = await start_task(conn, t.id, actor_id=seed_actor)
    done = await complete_task(conn, started.id, actor_id=seed_actor)
    assert done.context["status"] == "done"

    fixed = await edit_task(conn, done.id, actor_id=seed_actor, title="Fixed typo")

    assert fixed.title == "Fixed typo"
    assert fixed.context["status"] == "done"
