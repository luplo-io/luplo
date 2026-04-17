"""Tests for core.tasks.suggest_decision_from_task.

The contract: build a draft ``ItemCreate`` from a task, never insert it.
Returning ``None`` is the honest answer when there is nothing to
suggest.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from luplo.core.items import list_items
from luplo.core.tasks import (
    complete_task,
    create_task,
    start_task,
    suggest_decision_from_task,
)


async def _wu(conn: Any, project_id: str, actor_id: str) -> str:
    wu_id = str(uuid.uuid4())
    await conn.execute(
        "INSERT INTO work_units (id, project_id, title, created_by, status)"
        " VALUES (%s, %s, %s, %s, 'in_progress')",
        (wu_id, project_id, "Proposal WU", actor_id),
    )
    return wu_id


@pytest.mark.asyncio
async def test_suggest_returns_none_for_empty_task(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    """Task with no body and no summary yields no draft — honest silence."""
    wu = await _wu(conn, seed_project, seed_actor)
    t = await create_task(
        conn, project_id=seed_project, work_unit_id=wu, title="Empty task", actor_id=seed_actor
    )

    draft = await suggest_decision_from_task(conn, t.id)

    assert draft is None


@pytest.mark.asyncio
async def test_suggest_from_task_with_body(conn: Any, seed_project: str, seed_actor: str) -> None:
    wu = await _wu(conn, seed_project, seed_actor)
    t = await create_task(
        conn,
        project_id=seed_project,
        work_unit_id=wu,
        title="Pick JWT library",
        body="Evaluate pyjwt, authlib, python-jose for fit.",
        actor_id=seed_actor,
    )

    draft = await suggest_decision_from_task(conn, t.id)

    assert draft is not None
    assert draft.item_type == "decision"
    assert "Pick JWT library" in draft.title
    assert draft.body is not None
    assert "pyjwt" in draft.body
    assert draft.source_ref == f"task:{t.id}"
    assert "from_task" in draft.tags
    assert draft.work_unit_id == wu


@pytest.mark.asyncio
async def test_suggest_folds_summary_into_body(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    """Completion summary is incorporated as the outcome in the draft body."""
    wu = await _wu(conn, seed_project, seed_actor)
    t = await create_task(
        conn,
        project_id=seed_project,
        work_unit_id=wu,
        title="Pick JWT library",
        body="Compared pyjwt, authlib, python-jose.",
        actor_id=seed_actor,
    )
    started = await start_task(conn, t.id, actor_id=seed_actor)
    done = await complete_task(
        conn, started.id, actor_id=seed_actor, summary="Chose authlib — best OAuth coverage."
    )

    draft = await suggest_decision_from_task(conn, done.id)

    assert draft is not None
    assert draft.body is not None
    assert "Compared pyjwt" in draft.body
    assert "Outcome:" in draft.body
    assert "authlib" in draft.body


@pytest.mark.asyncio
async def test_suggest_does_not_insert(conn: Any, seed_project: str, seed_actor: str) -> None:
    """Calling suggest must NEVER create a new item — strict augment-not-replace."""
    wu = await _wu(conn, seed_project, seed_actor)
    t = await create_task(
        conn,
        project_id=seed_project,
        work_unit_id=wu,
        title="With body",
        body="some content",
        actor_id=seed_actor,
    )

    before = await list_items(conn, seed_project, limit=200)
    draft = await suggest_decision_from_task(conn, t.id)
    after = await list_items(conn, seed_project, limit=200)

    assert draft is not None
    assert len(after) == len(before), "suggest_decision must not insert"


@pytest.mark.asyncio
async def test_suggest_carries_work_unit_and_tags(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    """Draft inherits work_unit_id and merges task tags with a ``from_task`` marker."""
    wu = await _wu(conn, seed_project, seed_actor)
    t = await create_task(
        conn,
        project_id=seed_project,
        work_unit_id=wu,
        title="T",
        body="b",
        actor_id=seed_actor,
    )
    # Add a tag via edit
    from luplo.core.tasks import edit_task

    _ = await edit_task(conn, t.id, actor_id=seed_actor)
    # Tasks don't expose tag editing directly in v0.6; seed via raw SQL.
    await conn.execute("UPDATE items SET tags = ARRAY['infra','auth'] WHERE id = %s", (t.id,))

    draft = await suggest_decision_from_task(conn, t.id)

    assert draft is not None
    assert draft.work_unit_id == wu
    assert "from_task" in draft.tags
    assert "infra" in draft.tags
    assert "auth" in draft.tags
