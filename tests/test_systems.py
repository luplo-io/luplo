"""Integration tests for core/systems.py."""

from __future__ import annotations

import pytest
from psycopg.errors import UniqueViolation

from luplo.core.systems import (
    create_system,
    get_system,
    list_systems,
    update_system,
)


@pytest.mark.asyncio
async def test_create_system(conn: object, seed_project: str) -> None:
    s = await create_system(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        name="karma",
        description="Karma and reputation",
        depends_on_system_ids=["vendor", "pvp"],
    )
    assert s.id is not None
    assert s.project_id == seed_project
    assert s.name == "karma"
    assert s.description == "Karma and reputation"
    assert s.depends_on_system_ids == ["vendor", "pvp"]


@pytest.mark.asyncio
async def test_create_system_minimal(conn: object, seed_project: str) -> None:
    s = await create_system(conn, project_id=seed_project, name="bare")  # type: ignore[arg-type]
    assert s.description is None
    assert s.depends_on_system_ids == []
    assert s.status is None


@pytest.mark.asyncio
async def test_create_system_duplicate_name(
    conn: object, seed_project: str
) -> None:
    await create_system(conn, project_id=seed_project, name="dup")  # type: ignore[arg-type]
    with pytest.raises(UniqueViolation):
        await create_system(conn, project_id=seed_project, name="dup")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_get_system_found(conn: object, seed_project: str) -> None:
    created = await create_system(
        conn, project_id=seed_project, name="findme"  # type: ignore[arg-type]
    )
    fetched = await get_system(conn, created.id)  # type: ignore[arg-type]
    assert fetched is not None
    assert fetched.name == "findme"


@pytest.mark.asyncio
async def test_get_system_not_found(conn: object) -> None:
    assert await get_system(conn, "nope") is None  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_list_systems(conn: object, seed_project: str) -> None:
    await create_system(conn, project_id=seed_project, name="banking")  # type: ignore[arg-type]
    await create_system(conn, project_id=seed_project, name="vendor")  # type: ignore[arg-type]
    systems = await list_systems(conn, seed_project)  # type: ignore[arg-type]
    assert len(systems) == 2
    assert [s.name for s in systems] == ["banking", "vendor"]  # ordered by name


@pytest.mark.asyncio
async def test_list_systems_empty(conn: object, seed_project: str) -> None:
    systems = await list_systems(conn, seed_project)  # type: ignore[arg-type]
    assert systems == []


@pytest.mark.asyncio
async def test_update_system_single_field(
    conn: object, seed_project: str
) -> None:
    s = await create_system(
        conn, project_id=seed_project, name="updatable"  # type: ignore[arg-type]
    )
    updated = await update_system(
        conn, s.id, description="New desc"  # type: ignore[arg-type]
    )
    assert updated is not None
    assert updated.description == "New desc"
    assert updated.name == "updatable"  # unchanged


@pytest.mark.asyncio
async def test_update_system_multiple_fields(
    conn: object, seed_project: str
) -> None:
    s = await create_system(
        conn, project_id=seed_project, name="multi"  # type: ignore[arg-type]
    )
    updated = await update_system(
        conn,  # type: ignore[arg-type]
        s.id,
        description="Updated",
        status="active",
        depends_on_system_ids=["karma"],
    )
    assert updated is not None
    assert updated.description == "Updated"
    assert updated.status == "active"
    assert updated.depends_on_system_ids == ["karma"]


@pytest.mark.asyncio
async def test_update_system_clear_field(
    conn: object, seed_project: str
) -> None:
    s = await create_system(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        name="clearable",
        description="Will be cleared",
    )
    updated = await update_system(conn, s.id, description=None)  # type: ignore[arg-type]
    assert updated is not None
    assert updated.description is None


@pytest.mark.asyncio
async def test_update_system_no_changes(
    conn: object, seed_project: str
) -> None:
    s = await create_system(
        conn, project_id=seed_project, name="noop"  # type: ignore[arg-type]
    )
    updated = await update_system(conn, s.id)  # type: ignore[arg-type]
    assert updated is not None
    assert updated.name == "noop"


@pytest.mark.asyncio
async def test_update_system_not_found(conn: object) -> None:
    result = await update_system(conn, "ghost", status="dead")  # type: ignore[arg-type]
    assert result is None
