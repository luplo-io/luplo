"""Integration tests for core/actors.py.

After 0006_drop_auth:
  - actors.id is UUID (string form in Python).
  - actors.email is NOT NULL.
  - No authentication fields (password_hash, is_admin, last_login_at,
    oauth_provider, oauth_subject). actors are attribution labels only.
"""

from __future__ import annotations

import uuid

import pytest
from psycopg.errors import UniqueViolation

from luplo.core.actors import (
    create_actor,
    get_actor,
    get_actor_by_email,
)


def _uid() -> str:
    return str(uuid.uuid4())


@pytest.mark.asyncio
async def test_create_actor(conn: object) -> None:
    a = await create_actor(
        conn,  # type: ignore[arg-type]
        name="Taehun",
        email="taehun@luplo.io",
        role="maintainer",
        external_ids={"slack": "U123", "github": "hanyul99"},
    )
    assert a.id
    assert a.name == "Taehun"
    assert a.email == "taehun@luplo.io"
    assert a.role == "maintainer"
    assert a.external_ids == {"slack": "U123", "github": "hanyul99"}
    assert a.joined_at is not None


@pytest.mark.asyncio
async def test_create_actor_minimal(conn: object) -> None:
    a = await create_actor(
        conn,
        name="Ghost",
        email="ghost@test.com",  # type: ignore[arg-type]
    )
    assert a.email == "ghost@test.com"
    assert a.role is None
    assert a.external_ids == {}


@pytest.mark.asyncio
async def test_create_actor_custom_id(conn: object) -> None:
    explicit = _uid()
    a = await create_actor(
        conn,
        name="Bot",
        id=explicit,
        email="bot@test.com",  # type: ignore[arg-type]
    )
    assert a.id == explicit


@pytest.mark.asyncio
async def test_create_actor_duplicate_email(conn: object) -> None:
    await create_actor(
        conn,
        name="A",
        email="dup@test.com",  # type: ignore[arg-type]
    )
    with pytest.raises(UniqueViolation):
        await create_actor(
            conn,
            name="B",
            email="dup@test.com",  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_get_actor_found(conn: object) -> None:
    created = await create_actor(
        conn,
        name="FindMe",
        email="findme@test.com",  # type: ignore[arg-type]
    )
    fetched = await get_actor(conn, created.id)  # type: ignore[arg-type]
    assert fetched is not None
    assert fetched.name == "FindMe"


@pytest.mark.asyncio
async def test_get_actor_not_found(conn: object) -> None:
    missing = _uid()
    assert await get_actor(conn, missing) is None  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_get_actor_by_email_found(conn: object) -> None:
    await create_actor(
        conn,
        name="Email",
        email="find@test.com",  # type: ignore[arg-type]
    )
    found = await get_actor_by_email(conn, "find@test.com")  # type: ignore[arg-type]
    assert found is not None
    assert found.name == "Email"


@pytest.mark.asyncio
async def test_get_actor_by_email_not_found(conn: object) -> None:
    assert (
        await get_actor_by_email(
            conn,
            "nope@test.com",  # type: ignore[arg-type]
        )
        is None
    )
