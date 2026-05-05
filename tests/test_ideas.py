"""Integration tests for core/ideas.py — append-only with redact."""

from __future__ import annotations

import pytest

from luplo.core.ideas import add_idea, list_ideas, redact_idea, search_ideas
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
async def test_add_idea_rejects_missing_wu(conn: object, seed_project: str) -> None:
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
async def test_redact_idea_hides_from_default_list(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="x",
        created_by=seed_actor,
    )
    idea = await add_idea(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        work_unit_id=wu.id,
        text="oops sensitive thing",
        created_by=seed_actor,
    )

    redacted = await redact_idea(
        conn,  # type: ignore[arg-type]
        idea_id=idea.id,
        redacted_by=seed_actor,
    )
    assert redacted.redacted_at is not None
    assert redacted.redacted_by == seed_actor
    assert redacted.text == "oops sensitive thing"  # text preserved

    rows = await list_ideas(conn, work_unit_id=wu.id)  # type: ignore[arg-type]
    assert all(r.id != idea.id for r in rows)

    rows_with = await list_ideas(
        conn,  # type: ignore[arg-type]
        work_unit_id=wu.id,
        include_redacted=True,
    )
    assert any(r.id == idea.id for r in rows_with)


@pytest.mark.asyncio
async def test_redact_idea_is_idempotent(conn: object, seed_project: str, seed_actor: str) -> None:
    wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="x",
        created_by=seed_actor,
    )
    idea = await add_idea(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        work_unit_id=wu.id,
        text="x",
    )
    r1 = await redact_idea(
        conn,  # type: ignore[arg-type]
        idea_id=idea.id,
        redacted_by=seed_actor,
    )
    r2 = await redact_idea(
        conn,  # type: ignore[arg-type]
        idea_id=idea.id,
        redacted_by=seed_actor,
    )
    assert r1.redacted_at == r2.redacted_at  # second call is no-op


@pytest.mark.asyncio
async def test_redact_idea_missing_id_raises(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    with pytest.raises(ValueError, match="not found"):
        await redact_idea(
            conn,  # type: ignore[arg-type]
            idea_id="00000000-0000-0000-0000-000000000099",
            redacted_by=seed_actor,
        )


@pytest.mark.asyncio
async def test_search_ideas_simple_query(conn: object, seed_project: str, seed_actor: str) -> None:
    wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="auth",
        created_by=seed_actor,
    )
    await add_idea(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        work_unit_id=wu.id,
        text="refresh token swap on the frontend",
    )
    await add_idea(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        work_unit_id=wu.id,
        text="vendor inventory rotation",
    )

    rows = await search_ideas(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        query="refresh token",
    )
    assert len(rows) == 1
    assert "refresh" in rows[0].text


@pytest.mark.asyncio
async def test_search_ideas_filters_by_author(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    """`author` parameter scopes search to a single creator."""
    wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="multi-author",
        created_by=seed_actor,
    )
    other_actor = "00000000-0000-0000-0000-000000000002"
    await conn.execute(  # type: ignore[attr-defined]
        "INSERT INTO actors (id, name, email) VALUES (%s, %s, %s)",
        (other_actor, "Other", "other@x.io"),
    )
    await add_idea(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        work_unit_id=wu.id,
        text="mine",
        created_by=seed_actor,
    )
    await add_idea(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        work_unit_id=wu.id,
        text="theirs",
        created_by=other_actor,
    )

    mine = await search_ideas(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        author=seed_actor,
    )
    assert {r.text for r in mine} == {"mine"}


@pytest.mark.asyncio
async def test_search_ideas_excludes_redacted_by_default(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="x",
        created_by=seed_actor,
    )
    visible = await add_idea(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        work_unit_id=wu.id,
        text="visible token",
    )
    hidden = await add_idea(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        work_unit_id=wu.id,
        text="hidden token",
    )
    # Manually redact one — proper redact_idea comes in the next task.
    await conn.execute(  # type: ignore[attr-defined]
        "UPDATE ideas SET redacted_at = now(), redacted_by = %s WHERE id = %s",
        (seed_actor, hidden.id),
    )

    default_results = await search_ideas(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        query="token",
    )
    assert {r.id for r in default_results} == {visible.id}

    with_redacted = await search_ideas(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        query="token",
        include_redacted=True,
    )
    assert {r.id for r in with_redacted} == {visible.id, hidden.id}


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
        "UPDATE work_units SET status = 'done', closed_at = now() WHERE id = %s",
        (wu.id,),
    )
    idea = await add_idea(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        work_unit_id=wu.id,
        text="retro note: X turned out to work",
    )
    assert idea.id is not None
