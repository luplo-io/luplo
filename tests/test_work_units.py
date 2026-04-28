"""Integration tests for core/work_units.py."""

from __future__ import annotations

import pytest

from luplo.core.work_units import (
    archive_work_unit,
    close_work_unit,
    find_existing_import_wu,
    find_work_units,
    get_work_unit,
    list_work_units,
    open_work_unit,
)

# ── context round-trip ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_work_unit_roundtrips_context(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    """open_work_unit(context=...) is preserved through get_work_unit / list_work_units.

    Mirrors the items.context shape (added in 0003): a NOT NULL JSONB column
    that the import pipeline uses to stash dedup metadata per work unit.
    """
    payload = {
        "source_paths": ["docs/concepts/lp-import.md", "docs/guides/lp-import.md"],
        "imports": [
            {"path": "docs/concepts/lp-import.md", "hash": "deadbeef"},
        ],
    }

    created = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="Import bundle",
        created_by=seed_actor,
        context=payload,
    )
    assert created.context == payload

    fetched = await get_work_unit(conn, created.id)  # type: ignore[arg-type]
    assert fetched is not None
    assert fetched.context == payload

    listed = await list_work_units(conn, seed_project)  # type: ignore[arg-type]
    match = next((w for w in listed if w.id == created.id), None)
    assert match is not None
    assert match.context == payload


@pytest.mark.asyncio
async def test_open_work_unit_default_context_is_empty_dict(
    conn: object, seed_project: str
) -> None:
    """Omitting context yields an empty dict (matches the JSONB default ``'{}'``)."""
    wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="No context",
    )
    assert wu.context == {}


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


# ── archive_work_unit ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_archive_work_unit_sets_status_and_replaces_pointer(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    """archive_work_unit marks status='archived' and stamps replaced_by in context.

    Used by ``lp import --force`` to supersede a prior import bundle: the
    new wu is opened, the prior one is archived with a pointer to the
    successor.  Distinct from close_work_unit (status='done') and from
    abandoned (user gave up).
    """
    wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="To be archived",
        created_by=seed_actor,
    )

    archived = await archive_work_unit(
        conn,  # type: ignore[arg-type]
        wu.id,
        archived_by=seed_actor,
        replaced_by_wu_id="wu-new",
    )

    assert archived is not None
    assert archived.status == "archived"
    assert archived.closed_at is not None
    assert archived.closed_by == seed_actor
    assert archived.context.get("replaced_by") == "wu-new"


@pytest.mark.asyncio
async def test_archive_work_unit_preserves_existing_context(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    """Archiving merges replaced_by into context without dropping prior keys."""
    payload = {
        "source_paths": ["docs/concepts/lp-import.md"],
        "imports": [{"path": "docs/concepts/lp-import.md", "hash": "deadbeef"}],
    }
    wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="Archive with context",
        created_by=seed_actor,
        context=payload,
    )

    archived = await archive_work_unit(
        conn,  # type: ignore[arg-type]
        wu.id,
        archived_by=seed_actor,
        replaced_by_wu_id="wu-successor",
    )

    assert archived is not None
    assert archived.context.get("replaced_by") == "wu-successor"
    # Pre-existing keys must survive the JSONB merge.
    assert archived.context.get("source_paths") == payload["source_paths"]
    assert archived.context.get("imports") == payload["imports"]


@pytest.mark.asyncio
async def test_archive_work_unit_not_found(conn: object, seed_actor: str) -> None:
    """Archiving a nonexistent wu raises ValueError."""
    with pytest.raises(ValueError):
        await archive_work_unit(
            conn,  # type: ignore[arg-type]
            "00000000-dead-4dea-8dea-000000000000",
            archived_by=seed_actor,
            replaced_by_wu_id="wu-new",
        )


@pytest.mark.asyncio
async def test_archive_work_unit_refuses_already_closed_wu(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    """Archiving a wu that is already closed must not silently overwrite state.

    Mirrors the ``status='in_progress'`` guard on :func:`close_work_unit`:
    once the wu is in ``done``/``abandoned``/``archived``, archive must
    refuse rather than stomping ``status``, ``closed_at``, ``closed_by``,
    or any prior ``context.replaced_by`` pointer.
    """
    wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="Already done",
        created_by=seed_actor,
    )
    closed = await close_work_unit(
        conn,
        wu.id,
        actor_id=seed_actor,  # type: ignore[arg-type]
    )
    assert closed is not None and closed.status == "done"

    with pytest.raises(ValueError, match="not in 'in_progress' state"):
        await archive_work_unit(
            conn,  # type: ignore[arg-type]
            wu.id,
            archived_by=seed_actor,
            replaced_by_wu_id="wu-successor",
        )

    # Confirm the row was not mutated by the failed archive.
    refetched = await get_work_unit(conn, wu.id)  # type: ignore[arg-type]
    assert refetched is not None
    assert refetched.status == "done"
    assert refetched.context.get("replaced_by") is None


# ── find_existing_import_wu ──────────────────────────────────────


@pytest.mark.asyncio
async def test_find_existing_import_wu_matches_path_set(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    """Open an import wu, then a path-set lookup returns it.

    Used by ``lp import begin`` for dedup. Only ``context.kind == 'import'``
    work units count, and the stored ``source_paths`` are matched as a
    sorted set (order-insensitive).
    """
    paths = ("/abs/spec.md", "/abs/plan.md")

    found_initial = await find_existing_import_wu(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        source_paths=paths,
    )
    assert found_initial is None

    created = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="import 1",
        created_by=seed_actor,
        context={"source_paths": list(paths), "kind": "import"},
    )

    # Lookup is order-insensitive: pass paths in reversed order and still match.
    found_after = await find_existing_import_wu(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        source_paths=tuple(reversed(paths)),
    )
    assert found_after is not None
    assert found_after.id == created.id


@pytest.mark.asyncio
async def test_find_existing_import_wu_ignores_archived(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    """Archived import wus are not considered existing for dedup purposes."""
    paths = ("/abs/x.md",)

    created = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="old import",
        created_by=seed_actor,
        context={"source_paths": list(paths), "kind": "import"},
    )
    await archive_work_unit(
        conn,  # type: ignore[arg-type]
        created.id,
        archived_by=seed_actor,
        replaced_by_wu_id="wu-new",
    )

    found = await find_existing_import_wu(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        source_paths=paths,
    )
    # Archived ones are NOT considered existing for dedup purposes.
    assert found is None
