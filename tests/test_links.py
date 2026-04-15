"""Integration tests for core/links.py."""

from __future__ import annotations

import pytest
from psycopg.errors import UniqueViolation

from luplo.core.items import create_item
from luplo.core.links import create_link, delete_link, get_links
from luplo.core.models import ItemCreate


async def _make_item(conn: object, project: str, actor: str, title: str) -> str:
    """Helper: create an item and return its ID."""
    item = await create_item(
        conn,  # type: ignore[arg-type]
        ItemCreate(project_id=project, actor_id=actor, item_type="decision", title=title),
    )
    return item.id


@pytest.mark.asyncio
async def test_create_link(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    a = await _make_item(conn, seed_project, seed_actor, "Item A")
    b = await _make_item(conn, seed_project, seed_actor, "Item B")

    link = await create_link(
        conn,  # type: ignore[arg-type]
        from_item_id=a,
        to_item_id=b,
        link_type="excludes",
        strength=8,
        note="Mutually exclusive",
        actor_id=seed_actor,
    )

    assert link.from_item_id == a
    assert link.to_item_id == b
    assert link.link_type == "excludes"
    assert link.strength == 8
    assert link.note == "Mutually exclusive"
    assert link.created_by_actor_id == seed_actor


@pytest.mark.asyncio
async def test_create_link_defaults(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    a = await _make_item(conn, seed_project, seed_actor, "A")
    b = await _make_item(conn, seed_project, seed_actor, "B")

    link = await create_link(
        conn, from_item_id=a, to_item_id=b, link_type="related"  # type: ignore[arg-type]
    )
    assert link.strength == 5
    assert link.note is None
    assert link.created_by_actor_id is None


@pytest.mark.asyncio
async def test_create_link_duplicate(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    a = await _make_item(conn, seed_project, seed_actor, "A")
    b = await _make_item(conn, seed_project, seed_actor, "B")

    await create_link(
        conn, from_item_id=a, to_item_id=b, link_type="dup"  # type: ignore[arg-type]
    )
    with pytest.raises(UniqueViolation):
        await create_link(
            conn, from_item_id=a, to_item_id=b, link_type="dup"  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_get_links_from(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    a = await _make_item(conn, seed_project, seed_actor, "A")
    b = await _make_item(conn, seed_project, seed_actor, "B")
    c = await _make_item(conn, seed_project, seed_actor, "C")

    await create_link(conn, from_item_id=a, to_item_id=b, link_type="x")  # type: ignore[arg-type]
    await create_link(conn, from_item_id=a, to_item_id=c, link_type="y")  # type: ignore[arg-type]
    await create_link(conn, from_item_id=b, to_item_id=c, link_type="z")  # type: ignore[arg-type]

    links = await get_links(conn, a, direction="from")  # type: ignore[arg-type]
    assert len(links) == 2
    assert {l.to_item_id for l in links} == {b, c}


@pytest.mark.asyncio
async def test_get_links_to(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    a = await _make_item(conn, seed_project, seed_actor, "A")
    b = await _make_item(conn, seed_project, seed_actor, "B")
    c = await _make_item(conn, seed_project, seed_actor, "C")

    await create_link(conn, from_item_id=a, to_item_id=c, link_type="x")  # type: ignore[arg-type]
    await create_link(conn, from_item_id=b, to_item_id=c, link_type="y")  # type: ignore[arg-type]

    links = await get_links(conn, c, direction="to")  # type: ignore[arg-type]
    assert len(links) == 2
    assert {l.from_item_id for l in links} == {a, b}


@pytest.mark.asyncio
async def test_get_links_both(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    a = await _make_item(conn, seed_project, seed_actor, "A")
    b = await _make_item(conn, seed_project, seed_actor, "B")
    c = await _make_item(conn, seed_project, seed_actor, "C")

    await create_link(conn, from_item_id=a, to_item_id=b, link_type="x")  # type: ignore[arg-type]
    await create_link(conn, from_item_id=c, to_item_id=a, link_type="y")  # type: ignore[arg-type]

    links = await get_links(conn, a, direction="both")  # type: ignore[arg-type]
    assert len(links) == 2


@pytest.mark.asyncio
async def test_get_links_filter_type(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    a = await _make_item(conn, seed_project, seed_actor, "A")
    b = await _make_item(conn, seed_project, seed_actor, "B")

    await create_link(conn, from_item_id=a, to_item_id=b, link_type="excludes")  # type: ignore[arg-type]
    await create_link(conn, from_item_id=a, to_item_id=b, link_type="synergizes")  # type: ignore[arg-type]

    links = await get_links(
        conn, a, direction="from", link_type="excludes"  # type: ignore[arg-type]
    )
    assert len(links) == 1
    assert links[0].link_type == "excludes"


@pytest.mark.asyncio
async def test_get_links_empty(conn: object, seed_item: str) -> None:
    links = await get_links(conn, seed_item, direction="from")  # type: ignore[arg-type]
    assert links == []


@pytest.mark.asyncio
async def test_delete_link(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    a = await _make_item(conn, seed_project, seed_actor, "A")
    b = await _make_item(conn, seed_project, seed_actor, "B")

    await create_link(conn, from_item_id=a, to_item_id=b, link_type="x")  # type: ignore[arg-type]
    assert await delete_link(conn, a, b, "x") is True  # type: ignore[arg-type]
    assert await get_links(conn, a, direction="from") == []  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_delete_link_not_found(conn: object) -> None:
    result = await delete_link(conn, "a", "b", "nope")  # type: ignore[arg-type]
    assert result is False
