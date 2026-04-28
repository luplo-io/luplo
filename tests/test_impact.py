"""Tests for core/impact.py and the /items/{id}/impact HTTP route."""

from __future__ import annotations

from typing import Any

import pytest

from luplo.core.errors import NotFoundError, ValidationError
from luplo.core.impact import MAX_IMPACT_DEPTH, MIN_IMPACT_DEPTH, impact
from luplo.core.items import create_item
from luplo.core.links import create_link
from luplo.core.models import ItemCreate


async def _mk(conn: Any, project: str, actor: str, title: str) -> str:
    item = await create_item(
        conn,
        ItemCreate(project_id=project, actor_id=actor, item_type="decision", title=title),
    )
    return item.id


async def _link(conn: Any, src: str, dst: str, link_type: str = "depends") -> None:
    await create_link(conn, from_item_id=src, to_item_id=dst, link_type=link_type)


# ── Core impact() ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_impact_linear_chain(conn: Any, seed_project: str, seed_actor: str) -> None:
    a = await _mk(conn, seed_project, seed_actor, "A")
    b = await _mk(conn, seed_project, seed_actor, "B")
    c = await _mk(conn, seed_project, seed_actor, "C")
    await _link(conn, a, b, "depends")
    await _link(conn, b, c, "depends")

    result = await impact(conn, a, seed_project, depth=5)

    assert result.root.id == a
    ids = [n.item.id for n in result.nodes]
    assert ids == [b, c]
    assert [n.depth for n in result.nodes] == [1, 2]
    assert [n.via.link_type for n in result.nodes] == ["depends", "depends"]
    assert result.depth_requested == 5


@pytest.mark.asyncio
async def test_impact_depth_cap_honoured(conn: Any, seed_project: str, seed_actor: str) -> None:
    chain = [await _mk(conn, seed_project, seed_actor, f"I{i}") for i in range(7)]
    for i in range(6):
        await _link(conn, chain[i], chain[i + 1], "depends")

    result = await impact(conn, chain[0], seed_project, depth=3)

    assert [n.item.id for n in result.nodes] == [chain[1], chain[2], chain[3]]
    assert [n.depth for n in result.nodes] == [1, 2, 3]


@pytest.mark.asyncio
async def test_impact_depth_one_returns_only_neighbours(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    a = await _mk(conn, seed_project, seed_actor, "A")
    b = await _mk(conn, seed_project, seed_actor, "B")
    c = await _mk(conn, seed_project, seed_actor, "C")
    await _link(conn, a, b, "depends")
    await _link(conn, b, c, "depends")

    result = await impact(conn, a, seed_project, depth=1)

    assert [n.item.id for n in result.nodes] == [b]
    assert result.nodes[0].depth == 1


@pytest.mark.asyncio
async def test_impact_cycle_is_broken(conn: Any, seed_project: str, seed_actor: str) -> None:
    a = await _mk(conn, seed_project, seed_actor, "A")
    b = await _mk(conn, seed_project, seed_actor, "B")
    await _link(conn, a, b, "depends")
    await _link(conn, b, a, "depends")

    result = await impact(conn, a, seed_project, depth=5)

    assert [n.item.id for n in result.nodes] == [b]


@pytest.mark.asyncio
async def test_impact_diamond_dedup(conn: Any, seed_project: str, seed_actor: str) -> None:
    a = await _mk(conn, seed_project, seed_actor, "A")
    b = await _mk(conn, seed_project, seed_actor, "B")
    c = await _mk(conn, seed_project, seed_actor, "C")
    d = await _mk(conn, seed_project, seed_actor, "D")
    await _link(conn, a, b, "depends")
    await _link(conn, a, c, "depends")
    await _link(conn, b, d, "depends")
    await _link(conn, c, d, "depends")

    result = await impact(conn, a, seed_project, depth=5)

    ids = [n.item.id for n in result.nodes]
    assert sorted(ids) == sorted([b, c, d])
    assert ids.count(d) == 1
    d_node = next(n for n in result.nodes if n.item.id == d)
    assert d_node.depth == 2


@pytest.mark.asyncio
async def test_impact_multiple_edge_types(conn: Any, seed_project: str, seed_actor: str) -> None:
    a = await _mk(conn, seed_project, seed_actor, "A")
    b = await _mk(conn, seed_project, seed_actor, "B")
    c = await _mk(conn, seed_project, seed_actor, "C")
    d = await _mk(conn, seed_project, seed_actor, "D")
    await _link(conn, a, b, "depends")
    await _link(conn, a, c, "blocks")
    await _link(conn, a, d, "conflicts")

    result = await impact(conn, a, seed_project, depth=1)

    kinds = {n.item.id: n.via.link_type for n in result.nodes}
    assert kinds == {b: "depends", c: "blocks", d: "conflicts"}


@pytest.mark.asyncio
async def test_impact_non_traversable_link_type_ignored(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    a = await _mk(conn, seed_project, seed_actor, "A")
    b = await _mk(conn, seed_project, seed_actor, "B")
    await _link(conn, a, b, "related")

    result = await impact(conn, a, seed_project, depth=5)

    assert result.nodes == []


@pytest.mark.asyncio
async def test_impact_ignores_soft_deleted_target(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    a = await _mk(conn, seed_project, seed_actor, "A")
    b = await _mk(conn, seed_project, seed_actor, "B")
    await _link(conn, a, b, "depends")

    await conn.execute("UPDATE items SET deleted_at = now() WHERE id = %s", (b,))

    result = await impact(conn, a, seed_project, depth=5)

    assert result.nodes == []


@pytest.mark.asyncio
async def test_impact_does_not_cross_projects(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    other = "other-project"
    await conn.execute(
        "INSERT INTO projects (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (other, "Other"),
    )
    a = await _mk(conn, seed_project, seed_actor, "A")
    b_other = await _mk(conn, other, seed_actor, "B in other")
    await _link(conn, a, b_other, "depends")

    result = await impact(conn, a, seed_project, depth=5)

    assert result.nodes == []


@pytest.mark.asyncio
async def test_impact_unknown_root_raises(conn: Any, seed_project: str) -> None:
    missing = "99999999-9999-9999-9999-999999999999"
    with pytest.raises(NotFoundError):
        await impact(conn, missing, seed_project, depth=5)


@pytest.mark.asyncio
async def test_impact_depth_out_of_range_raises(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    a = await _mk(conn, seed_project, seed_actor, "A")

    with pytest.raises(ValidationError):
        await impact(conn, a, seed_project, depth=MIN_IMPACT_DEPTH - 1)
    with pytest.raises(ValidationError):
        await impact(conn, a, seed_project, depth=MAX_IMPACT_DEPTH + 1)


@pytest.mark.asyncio
async def test_impact_no_edges(conn: Any, seed_project: str, seed_actor: str) -> None:
    a = await _mk(conn, seed_project, seed_actor, "A")

    result = await impact(conn, a, seed_project, depth=5)

    assert result.root.id == a
    assert result.nodes == []
    assert result.depth_requested == 5


@pytest.mark.asyncio
async def test_impact_prefix_resolves_root(conn: Any, seed_project: str, seed_actor: str) -> None:
    a = await _mk(conn, seed_project, seed_actor, "A")
    b = await _mk(conn, seed_project, seed_actor, "B")
    await _link(conn, a, b, "depends")

    result = await impact(conn, a[:8], seed_project, depth=5)

    assert result.root.id == a
    assert [n.item.id for n in result.nodes] == [b]


