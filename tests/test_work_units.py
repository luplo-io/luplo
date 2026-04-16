"""Integration tests for core/work_units.py."""

from __future__ import annotations

import pytest

from luplo.core.work_units import (
    close_work_unit,
    find_work_units,
    get_work_unit,
    list_work_units,
    open_work_unit,
)


# ── open_work_unit ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_work_unit(conn: object, seed_project: str, seed_actor: str) -> None:
    wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="Vendor system design",
        description="Full vendor rework",
        system_ids=["vendor", "karma"],
        created_by=seed_actor,
    )

    assert wu.id is not None
    assert wu.project_id == seed_project
    assert wu.title == "Vendor system design"
    assert wu.description == "Full vendor rework"
    assert wu.system_ids == ["vendor", "karma"]
    assert wu.status == "in_progress"
    assert wu.created_by == seed_actor
    assert wu.closed_at is None
    assert wu.closed_by is None


@pytest.mark.asyncio
async def test_open_work_unit_minimal(conn: object, seed_project: str) -> None:
    wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="Quick task",
    )

    assert wu.title == "Quick task"
    assert wu.description is None
    assert wu.system_ids == []
    assert wu.created_by is None


# ── get_work_unit ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_work_unit_found(conn: object, seed_project: str) -> None:
    created = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="Findable",
    )
    fetched = await get_work_unit(conn, created.id)  # type: ignore[arg-type]

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.title == "Findable"


@pytest.mark.asyncio
async def test_get_work_unit_not_found(conn: object) -> None:
    result = await get_work_unit(
        conn,  # type: ignore[arg-type]
        "00000000-dead-4dea-8dea-000000000000",
    )
    assert result is None


# ── list_work_units ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_work_units_all(conn: object, seed_project: str, seed_actor: str) -> None:
    await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="WU A",
    )
    wu_b = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="WU B",
    )
    await close_work_unit(
        conn,
        wu_b.id,
        actor_id=seed_actor,  # type: ignore[arg-type]
    )

    all_wus = await list_work_units(conn, seed_project)  # type: ignore[arg-type]
    assert len(all_wus) == 2


@pytest.mark.asyncio
async def test_list_work_units_filter_status(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="Active",
    )
    done_wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="Finished",
    )
    await close_work_unit(
        conn,
        done_wu.id,
        actor_id=seed_actor,  # type: ignore[arg-type]
    )

    active = await list_work_units(
        conn,
        seed_project,
        status="in_progress",  # type: ignore[arg-type]
    )
    assert len(active) == 1
    assert active[0].title == "Active"

    done = await list_work_units(
        conn,
        seed_project,
        status="done",  # type: ignore[arg-type]
    )
    assert len(done) == 1
    assert done[0].title == "Finished"


# ── find_work_units ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_work_units_by_title(conn: object, seed_project: str) -> None:
    await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="Vendor system design",
    )
    await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="Karma rework",
    )

    results = await find_work_units(
        conn,
        seed_project,
        "vendor",  # type: ignore[arg-type]
    )
    assert len(results) == 1
    assert results[0].title == "Vendor system design"


@pytest.mark.asyncio
async def test_find_work_units_case_insensitive(conn: object, seed_project: str) -> None:
    await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="Vendor System Design",
    )

    results = await find_work_units(
        conn,
        seed_project,
        "vendor",  # type: ignore[arg-type]
    )
    assert len(results) == 1


@pytest.mark.asyncio
async def test_find_work_units_excludes_closed(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="Done vendor work",
    )
    await close_work_unit(
        conn,
        wu.id,
        actor_id=seed_actor,  # type: ignore[arg-type]
    )

    results = await find_work_units(
        conn,
        seed_project,
        "vendor",  # type: ignore[arg-type]
    )
    assert len(results) == 0


@pytest.mark.asyncio
async def test_find_work_units_no_match(conn: object, seed_project: str) -> None:
    await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="Karma rework",
    )

    results = await find_work_units(
        conn,
        seed_project,
        "vendor",  # type: ignore[arg-type]
    )
    assert len(results) == 0


# ── close_work_unit ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_work_unit_done(conn: object, seed_project: str, seed_actor: str) -> None:
    wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="Will be done",
        created_by=seed_actor,
    )
    closed = await close_work_unit(
        conn,
        wu.id,
        actor_id=seed_actor,  # type: ignore[arg-type]
    )

    assert closed is not None
    assert closed.status == "done"
    assert closed.closed_at is not None
    assert closed.closed_by == seed_actor


@pytest.mark.asyncio
async def test_close_work_unit_abandoned(conn: object, seed_project: str, seed_actor: str) -> None:
    wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="Will be abandoned",
    )
    closed = await close_work_unit(
        conn,
        wu.id,
        actor_id=seed_actor,
        status="abandoned",  # type: ignore[arg-type]
    )

    assert closed is not None
    assert closed.status == "abandoned"


@pytest.mark.asyncio
async def test_close_work_unit_handoff(conn: object, seed_project: str, seed_actor: str) -> None:
    """A→B handoff: created_by != closed_by."""
    # Create a second actor (UUID + email required after 0002).
    actor_b = "00000000-0000-0000-0000-000000000002"
    await conn.execute(  # type: ignore[union-attr]
        "INSERT INTO actors (id, name, email) VALUES (%s, %s, %s)",
        (actor_b, "Developer B", "dev-b@test.com"),
    )

    wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="Handoff task",
        created_by=seed_actor,
    )
    closed = await close_work_unit(
        conn,
        wu.id,
        actor_id=actor_b,  # type: ignore[arg-type]
    )

    assert closed is not None
    assert closed.created_by == seed_actor
    assert closed.closed_by == actor_b


@pytest.mark.asyncio
async def test_close_work_unit_already_closed(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="Close twice",
    )
    await close_work_unit(
        conn,
        wu.id,
        actor_id=seed_actor,  # type: ignore[arg-type]
    )
    result = await close_work_unit(
        conn,
        wu.id,
        actor_id=seed_actor,  # type: ignore[arg-type]
    )

    assert result is None


@pytest.mark.asyncio
async def test_close_work_unit_not_found(conn: object, seed_actor: str) -> None:
    result = await close_work_unit(
        conn,
        "ghost",
        actor_id=seed_actor,  # type: ignore[arg-type]
    )
    assert result is None
