"""Integration tests for core/ideas.py — append-only with redact."""

from __future__ import annotations

import pytest

from luplo.core.ideas import add_idea, list_ideas
from luplo.core.work_units import open_work_unit


@pytest.mark.asyncio
async def test_add_idea_persists_text_and_links_to_wu(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="brainstorm session",
        created_by=seed_actor,
    )

    idea = await add_idea(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        work_unit_id=wu.id,
        text="refresh token swap on the frontend",
        created_by=seed_actor,
    )

    assert idea.text == "refresh token swap on the frontend"
    assert idea.work_unit_id == wu.id
    assert idea.project_id == seed_project
    assert idea.created_by == seed_actor
    assert idea.created_at is not None
    assert idea.redacted_at is None

    rows = await list_ideas(
        conn,  # type: ignore[arg-type]
        work_unit_id=wu.id,
    )
    assert len(rows) == 1
    assert rows[0].id == idea.id


@pytest.mark.asyncio
async def test_add_idea_rejects_empty_text(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="x",
        created_by=seed_actor,
    )
    with pytest.raises(ValueError, match="empty"):
        await add_idea(
            conn,  # type: ignore[arg-type]
            project_id=seed_project,
            work_unit_id=wu.id,
            text="",
        )
    with pytest.raises(ValueError, match="empty"):
        await add_idea(
            conn,  # type: ignore[arg-type]
            project_id=seed_project,
            work_unit_id=wu.id,
            text="   \n  ",  # whitespace-only
        )


@pytest.mark.asyncio
async def test_add_idea_rejects_missing_wu(
    conn: object, seed_project: str
) -> None:
    with pytest.raises(ValueError, match="not found"):
        await add_idea(
            conn,  # type: ignore[arg-type]
            project_id=seed_project,
            work_unit_id="does-not-exist",
            text="orphan",
        )


@pytest.mark.asyncio
async def test_add_idea_rejects_cross_project_wu(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    # WU exists but in a different project — must reject.
    other_pid = "test-project-other"
    await conn.execute(  # type: ignore[attr-defined]
        "INSERT INTO projects (id, name) VALUES (%s, %s)",
        (other_pid, "Other"),
    )
    other_wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=other_pid,
        title="other",
        created_by=seed_actor,
    )
    with pytest.raises(ValueError, match="different project"):
        await add_idea(
            conn,  # type: ignore[arg-type]
            project_id=seed_project,
            work_unit_id=other_wu.id,
            text="cross-project leak",
        )


@pytest.mark.asyncio
async def test_add_idea_rejects_archived_wu(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="x",
        created_by=seed_actor,
    )
    await conn.execute(  # type: ignore[attr-defined]
        "UPDATE work_units SET status = 'archived' WHERE id = %s",
        (wu.id,),
    )
    with pytest.raises(ValueError, match="archived"):
        await add_idea(
            conn,  # type: ignore[arg-type]
            project_id=seed_project,
            work_unit_id=wu.id,
            text="too late",
        )


@pytest.mark.asyncio
async def test_add_idea_allowed_on_done_wu(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    """Closed (done) WUs accept ideas — retro notes use case."""
    wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="x",
        created_by=seed_actor,
    )
    await conn.execute(  # type: ignore[attr-defined]
        "UPDATE work_units SET status = 'done', closed_at = now()"
        " WHERE id = %s",
        (wu.id,),
    )
    idea = await add_idea(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        work_unit_id=wu.id,
        text="retro note: X turned out to work",
    )
    assert idea.id is not None
