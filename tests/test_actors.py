"""Integration tests for core/actors.py.

After 0002_auth_redesign:
  - actors.id is UUID (string form in Python).
  - actors.email is NOT NULL.
"""

from __future__ import annotations

import uuid

import pytest
from psycopg.errors import UniqueViolation

from luplo.core.actors import (
    create_actor,
    get_actor,
    get_actor_by_email,
    set_admin,
    set_password,
    touch_login,
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
    assert a.is_admin is False
    assert a.password_hash is None


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


@pytest.mark.asyncio
async def test_set_password(conn: object) -> None:
    a = await create_actor(
        conn,
        name="Pw",
        email="pw@test.com",  # type: ignore[arg-type]
    )
    await set_password(conn, a.id, "hashedvalue")  # type: ignore[arg-type]
    refetched = await get_actor(conn, a.id)  # type: ignore[arg-type]
    assert refetched is not None
    assert refetched.password_hash == "hashedvalue"


@pytest.mark.asyncio
async def test_set_admin(conn: object) -> None:
    a = await create_actor(
        conn,
        name="Adm",
        email="adm@test.com",  # type: ignore[arg-type]
    )
    await set_admin(conn, a.id, True)  # type: ignore[arg-type]
    refetched = await get_actor(conn, a.id)  # type: ignore[arg-type]
    assert refetched is not None
    assert refetched.is_admin is True


@pytest.mark.asyncio
async def test_touch_login(conn: object) -> None:
    a = await create_actor(
        conn,
        name="Lg",
        email="lg@test.com",  # type: ignore[arg-type]
    )
    await touch_login(conn, a.id)  # type: ignore[arg-type]
    refetched = await get_actor(conn, a.id)  # type: ignore[arg-type]
    assert refetched is not None
    assert refetched.last_login_at is not None
