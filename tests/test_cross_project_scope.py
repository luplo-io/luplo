"""Tests for v0.6 mutator project scope propagation.

Each mutator that accepts a ``task_id`` or ``qa_id`` prefix now takes an
optional ``project_id`` keyword. When supplied, prefix resolution is
constrained to that project, so a prefix that happens to match a row in
another project can never silently mutate that other row.
"""

from __future__ import annotations

from typing import Any

import pytest

from luplo.core.errors import TaskNotFoundError
from luplo.core.items import create_item
from luplo.core.models import ItemCreate
from luplo.core.tasks import create_task, start_task


async def _other_project(conn: Any, pid: str) -> None:
    await conn.execute(
        "INSERT INTO projects (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (pid, f"Project {pid}"),
    )


async def _wu(conn: Any, project_id: str, actor_id: str, title: str) -> str:
    """Create a work unit and return its id."""
    import uuid

    wu_id = str(uuid.uuid4())
    await conn.execute(
        "INSERT INTO work_units (id, project_id, title, created_by, status)"
        " VALUES (%s, %s, %s, %s, 'in_progress')",
        (wu_id, project_id, title, actor_id),
    )
    return wu_id


@pytest.mark.asyncio
async def test_start_task_scoped_to_project_ignores_other_project_match(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    """Prefix resolution respects project scope: a task living only in
    project B is invisible to ``start_task`` called with ``project_id=A``,
    even though the prefix uniquely identifies the row globally."""
    other = "other-scope"
    await _other_project(conn, other)

    wu_a = await _wu(conn, seed_project, seed_actor, "WU A")
    wu_b = await _wu(conn, other, seed_actor, "WU B")

    task_a = await create_task(
        conn, project_id=seed_project, work_unit_id=wu_a, title="A", actor_id=seed_actor
    )
    task_b = await create_task(
        conn, project_id=other, work_unit_id=wu_b, title="B", actor_id=seed_actor
    )

    # Sanity: both rows exist with distinct ids.
    assert task_a.id != task_b.id

    # Call start_task from project A with a prefix that matches ONLY task_b.
    # Without project scope, this would silently start B's task. With scope,
    # it must raise TaskNotFoundError.
    prefix_b = task_b.id[:8]
    with pytest.raises(TaskNotFoundError):
        await start_task(
            conn,
            prefix_b,
            actor_id=seed_actor,
            project_id=seed_project,
        )


@pytest.mark.asyncio
async def test_start_task_with_matching_project_succeeds(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    """Sanity: scoped resolution still works when the prefix matches the
    caller's project."""
    wu = await _wu(conn, seed_project, seed_actor, "WU scoped")
    task = await create_task(
        conn,
        project_id=seed_project,
        work_unit_id=wu,
        title="Scoped",
        actor_id=seed_actor,
    )

    started = await start_task(
        conn,
        task.id[:8],
        actor_id=seed_actor,
        project_id=seed_project,
    )
    assert started.context.get("status") == "in_progress"


@pytest.mark.asyncio
async def test_start_task_without_scope_still_resolves_globally(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    """Backwards compat: omitting ``project_id`` keeps the pre-v0.6 behaviour
    of resolving across all projects. This is preserved so v0.5 callers do
    not break; CLI and MCP always pass the scope in v0.6."""
    wu = await _wu(conn, seed_project, seed_actor, "WU compat")
    task = await create_task(
        conn, project_id=seed_project, work_unit_id=wu, title="Compat", actor_id=seed_actor
    )

    started = await start_task(conn, task.id[:8], actor_id=seed_actor)
    assert started.context.get("status") == "in_progress"


@pytest.mark.asyncio
async def test_mutator_scope_defends_against_id_typo_into_other_project(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    """Regression for the v0.5.x residual risk: a user in project A types a
    short prefix intending to target A's task, but the prefix happens to match
    a row in project B. With scope, the mutator refuses rather than
    mutating B."""
    other = "typo-target-project"
    await _other_project(conn, other)

    # Create an item in 'other' whose id we'll pretend to 'typo' into.
    decoy = await create_item(
        conn,
        ItemCreate(
            project_id=other,
            actor_id=seed_actor,
            item_type="task",
            title="Decoy B-task",
            context={"status": "proposed", "sort_order": 10},
        ),
    )

    # Same prefix must not resolve in seed_project.
    with pytest.raises(TaskNotFoundError):
        await start_task(
            conn,
            decoy.id[:8],
            actor_id=seed_actor,
            project_id=seed_project,
        )


@pytest.mark.asyncio
async def test_mutator_scope_picks_correct_project_when_same_prefix_in_both(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    """Hardest case: the same 8-char prefix exists in BOTH projects, one task
    per project. With ``project_id`` scope, the mutator must resolve to
    exactly the caller's row — never to the other project's row, never
    ambiguous.

    We force the collision by creating two tasks with IDs that share their
    first 8 hex characters. Items.id is TEXT (not UUID-typed), so inserting
    custom IDs is legitimate here — the scenario we're defending against
    is the rare but real case where natural UUIDs collide on the 8-char
    prefix the CLI displays.
    """
    import uuid

    other = "twin-prefix-project"
    await _other_project(conn, other)

    wu_a = await _wu(conn, seed_project, seed_actor, "WU A")
    wu_b = await _wu(conn, other, seed_actor, "WU B")

    # Contrive a shared 8-char prefix.
    shared_prefix = "cafebabe"
    id_a = f"{shared_prefix}-0000-4000-8000-000000000001"
    id_b = f"{shared_prefix}-0000-4000-8000-000000000002"

    await conn.execute(
        "INSERT INTO items (id, project_id, item_type, title, actor_id,"
        " work_unit_id, search_tsv, context)"
        " VALUES (%s, %s, 'task', %s, %s, %s, to_tsvector('simple', %s),"
        ' \'{"status": "proposed", "sort_order": 10}\'::jsonb)',
        (id_a, seed_project, "Twin A", seed_actor, wu_a, "Twin A"),
    )
    await conn.execute(
        "INSERT INTO items (id, project_id, item_type, title, actor_id,"
        " work_unit_id, search_tsv, context)"
        " VALUES (%s, %s, 'task', %s, %s, %s, to_tsvector('simple', %s),"
        ' \'{"status": "proposed", "sort_order": 10}\'::jsonb)',
        (id_b, other, "Twin B", seed_actor, wu_b, "Twin B"),
    )

    # Scope to seed_project — must resolve to id_a (Twin A), not error out
    # with ambiguity, not pick id_b.
    started = await start_task(
        conn,
        shared_prefix,
        actor_id=seed_actor,
        project_id=seed_project,
    )
    # The started row is a new supersede row; its chain root is id_a.
    assert started.supersedes_id == id_a
    assert started.project_id == seed_project
    assert started.title == "Twin A"

    # Confirm id_b's chain in the other project is untouched.
    row = await conn.execute("SELECT COUNT(*) FROM items WHERE supersedes_id = %s", (id_b,))
    count_b_supersedes = (await row.fetchone())[0]
    assert count_b_supersedes == 0, "Twin B must not have been started"

    # Sanity: without scope, the same prefix resolves to BOTH heads and
    # raises AmbiguousIdError — this is what scope defends against.
    from luplo.core.errors import AmbiguousIdError

    _ = uuid  # keep import (suppress lint)
    with pytest.raises(AmbiguousIdError):
        await start_task(conn, shared_prefix, actor_id=seed_actor)
