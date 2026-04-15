"""Integration tests for core/projects.py."""

from __future__ import annotations

import pytest
from psycopg.errors import UniqueViolation

from luplo.core.projects import create_project, get_project, list_projects


@pytest.mark.asyncio
async def test_create_project(conn: object) -> None:
    p = await create_project(conn, name="hearthward", description="MMORPG")  # type: ignore[arg-type]
    assert p.id is not None
    assert p.name == "hearthward"
    assert p.description == "MMORPG"
    assert p.created_at is not None


@pytest.mark.asyncio
async def test_create_project_minimal(conn: object) -> None:
    p = await create_project(conn, name="bare")  # type: ignore[arg-type]
    assert p.description is None


@pytest.mark.asyncio
async def test_create_project_custom_id(conn: object) -> None:
    p = await create_project(conn, name="custom", id="my-id")  # type: ignore[arg-type]
    assert p.id == "my-id"


@pytest.mark.asyncio
async def test_create_project_duplicate_name(conn: object) -> None:
    await create_project(conn, name="dup")  # type: ignore[arg-type]
    with pytest.raises(UniqueViolation):
        await create_project(conn, name="dup")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_get_project_found(conn: object) -> None:
    created = await create_project(conn, name="findme")  # type: ignore[arg-type]
    fetched = await get_project(conn, created.id)  # type: ignore[arg-type]
    assert fetched is not None
    assert fetched.name == "findme"


@pytest.mark.asyncio
async def test_get_project_not_found(conn: object) -> None:
    assert await get_project(conn, "nope") is None  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_list_projects(conn: object) -> None:
    await create_project(conn, name="alpha")  # type: ignore[arg-type]
    await create_project(conn, name="beta")  # type: ignore[arg-type]
    projects = await list_projects(conn)  # type: ignore[arg-type]
    assert len(projects) == 2
    assert {p.name for p in projects} == {"alpha", "beta"}


@pytest.mark.asyncio
async def test_list_projects_empty(conn: object) -> None:
    projects = await list_projects(conn)  # type: ignore[arg-type]
    assert projects == []
