"""Integration tests for core/items.py — runs against a real PostgreSQL."""

from __future__ import annotations

import pytest

from luplo.core.items import (
    create_item,
    delete_item,
    get_item,
    get_item_including_deleted,
    get_supersedes_chain,
    list_items,
)
from luplo.core.models import ItemCreate

# ── Helpers ──────────────────────────────────────────────────────


def _decision(project_id: str, actor_id: str, **overrides: object) -> ItemCreate:
    """Build an ``ItemCreate`` with sensible defaults for a decision."""
    defaults = {
        "project_id": project_id,
        "actor_id": actor_id,
        "item_type": "decision",
        "title": "Default title",
    }
    defaults.update(overrides)
    return ItemCreate(**defaults)  # type: ignore[arg-type]


# ── create_item ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_item_returns_populated_item(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    item = await create_item(
        conn,  # type: ignore[arg-type]
        _decision(
            seed_project,
            seed_actor,
            title="Use PostgreSQL",
            body="Single DB for everything.",
            rationale="Best combo of tsquery + JSONB + pgvector.",
            system_ids=["infra"],
            tags=["database", "architecture"],
        ),
    )

    assert item.id is not None
    assert item.project_id == seed_project
    assert item.actor_id == seed_actor
    assert item.item_type == "decision"
    assert item.title == "Use PostgreSQL"
    assert item.body == "Single DB for everything."
    assert item.rationale == "Best combo of tsquery + JSONB + pgvector."
    assert item.system_ids == ["infra"]
    assert item.tags == ["database", "architecture"]
    assert item.deleted_at is None
    assert item.created_at is not None


@pytest.mark.asyncio
async def test_create_item_with_supersedes(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    original = await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="V1"),
    )
    revised = await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="V2", supersedes_id=original.id),
    )

    assert revised.supersedes_id == original.id
    assert revised.id != original.id


@pytest.mark.asyncio
async def test_create_item_minimal_fields(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    """Only required fields — everything else should default cleanly."""
    item = await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="Bare minimum"),
    )

    assert item.body is None
    assert item.rationale is None
    assert item.system_ids == []
    assert item.tags == []
    assert item.alternatives is None
    assert item.supersedes_id is None


# ── get_item ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_item_found(conn: object, seed_project: str, seed_actor: str) -> None:
    created = await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="Findable"),
    )
    fetched = await get_item(conn, created.id)  # type: ignore[arg-type]

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.title == "Findable"


@pytest.mark.asyncio
async def test_get_item_not_found(conn: object) -> None:
    # Use a syntactically valid full UUID that hasn't been seeded.
    result = await get_item(
        conn,  # type: ignore[arg-type]
        "00000000-dead-4dea-8dea-000000000000",
    )
    assert result is None


@pytest.mark.asyncio
async def test_get_item_hides_soft_deleted(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    item = await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="Will be deleted"),
    )
    await delete_item(conn, item.id, actor_id=seed_actor)  # type: ignore[arg-type]

    assert await get_item(conn, item.id) is None  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_get_item_including_deleted(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    item = await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="Soft deleted"),
    )
    await delete_item(conn, item.id, actor_id=seed_actor)  # type: ignore[arg-type]

    fetched = await get_item_including_deleted(conn, item.id)  # type: ignore[arg-type]
    assert fetched is not None
    assert fetched.deleted_at is not None


# ── list_items ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_items_basic(conn: object, seed_project: str, seed_actor: str) -> None:
    await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="Item A"),
    )
    await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="Item B"),
    )

    items = await list_items(conn, seed_project)  # type: ignore[arg-type]
    assert len(items) == 2
    assert {i.title for i in items} == {"Item A", "Item B"}


@pytest.mark.asyncio
async def test_list_items_excludes_deleted(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    item = await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="Doomed"),
    )
    await delete_item(conn, item.id, actor_id=seed_actor)  # type: ignore[arg-type]

    items = await list_items(conn, seed_project)  # type: ignore[arg-type]
    assert all(i.id != item.id for i in items)


@pytest.mark.asyncio
async def test_list_items_include_deleted(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    item = await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="Doomed but visible"),
    )
    await delete_item(conn, item.id, actor_id=seed_actor)  # type: ignore[arg-type]

    items = await list_items(
        conn,
        seed_project,
        include_deleted=True,  # type: ignore[arg-type]
    )
    assert any(i.id == item.id for i in items)


@pytest.mark.asyncio
async def test_list_items_filter_by_type(conn: object, seed_project: str, seed_actor: str) -> None:
    await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="A decision"),
    )
    await create_item(
        conn,  # type: ignore[arg-type]
        ItemCreate(
            project_id=seed_project,
            actor_id=seed_actor,
            item_type="knowledge",
            title="A fact",
        ),
    )

    decisions = await list_items(
        conn,
        seed_project,
        item_type="decision",  # type: ignore[arg-type]
    )
    assert len(decisions) == 1
    assert decisions[0].item_type == "decision"


@pytest.mark.asyncio
async def test_list_items_filter_by_system(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="Karma rule", system_ids=["karma"]),
    )
    await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="Vendor rule", system_ids=["vendor"]),
    )

    karma_items = await list_items(
        conn,
        seed_project,
        system_id="karma",  # type: ignore[arg-type]
    )
    assert len(karma_items) == 1
    assert karma_items[0].title == "Karma rule"


@pytest.mark.asyncio
async def test_list_items_filter_by_work_unit(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    # Create a work unit first (full UUID — work_units.id is TEXT but
    # _resolve_work_unit_id treats anything that's not a UUID/prefix as
    # invalid format. Use a real UUID here.)
    wu_id = "11111111-2222-4333-8444-555555555555"
    await conn.execute(  # type: ignore[union-attr]
        "INSERT INTO work_units (id, project_id, title, created_by) VALUES (%s, %s, %s, %s)",
        (wu_id, seed_project, "Design sprint", seed_actor),
    )

    await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="In WU", work_unit_id=wu_id),
    )
    await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="No WU"),
    )

    items = await list_items(
        conn,
        seed_project,
        work_unit_id=wu_id,  # type: ignore[arg-type]
    )
    assert len(items) == 1
    assert items[0].title == "In WU"


@pytest.mark.asyncio
async def test_create_item_resolves_work_unit_prefix(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    """create_item must accept a work_unit_id hex prefix, not just full UUID.

    Regression for the release-blocking bug where `lp items add --wu <prefix>`
    raised an FK-violation traceback because the CLI passed the displayed
    8-char prefix straight through to INSERT.
    """
    wu_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    await conn.execute(  # type: ignore[union-attr]
        "INSERT INTO work_units (id, project_id, title, created_by) VALUES (%s, %s, %s, %s)",
        (wu_id, seed_project, "Prefix WU", seed_actor),
    )

    item = await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="ByPrefix", work_unit_id=wu_id[:8]),
    )
    assert item.work_unit_id == wu_id

    filtered = await list_items(
        conn,  # type: ignore[arg-type]
        seed_project,
        work_unit_id=wu_id[:8],
    )
    assert any(i.title == "ByPrefix" for i in filtered)


@pytest.mark.asyncio
async def test_list_items_returns_chain_head_only(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    """list_items must return only the head of each supersede chain.

    A chain head is a row with no successor. Returning intermediate rows
    breaks the head-identity contract: the user could copy a stale ID
    into a new supersede call.
    """
    v1 = await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="V1"),
    )
    v2 = await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="V2", supersedes_id=v1.id),
    )
    v3 = await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="V3", supersedes_id=v2.id),
    )

    items = await list_items(conn, seed_project)  # type: ignore[arg-type]
    ids = {i.id for i in items}
    assert v3.id in ids
    assert v1.id not in ids
    assert v2.id not in ids


@pytest.mark.asyncio
async def test_list_items_pagination(conn: object, seed_project: str, seed_actor: str) -> None:
    for i in range(5):
        await create_item(
            conn,  # type: ignore[arg-type]
            _decision(seed_project, seed_actor, title=f"Item {i}"),
        )

    page1 = await list_items(conn, seed_project, limit=2, offset=0)  # type: ignore[arg-type]
    page2 = await list_items(conn, seed_project, limit=2, offset=2)  # type: ignore[arg-type]

    assert len(page1) == 2
    assert len(page2) == 2
    assert page1[0].id != page2[0].id


# ── delete_item ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_item_returns_true(conn: object, seed_project: str, seed_actor: str) -> None:
    item = await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="Delete me"),
    )
    result = await delete_item(conn, item.id, actor_id=seed_actor)  # type: ignore[arg-type]
    assert result is True


@pytest.mark.asyncio
async def test_delete_item_idempotent(conn: object, seed_project: str, seed_actor: str) -> None:
    item = await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="Delete twice"),
    )
    await delete_item(conn, item.id, actor_id=seed_actor)  # type: ignore[arg-type]
    result = await delete_item(conn, item.id, actor_id=seed_actor)  # type: ignore[arg-type]
    assert result is False


@pytest.mark.asyncio
async def test_delete_nonexistent_returns_false(conn: object) -> None:
    result = await delete_item(
        conn,
        "ghost",
        actor_id="00000000-0000-0000-0000-00000000dead",  # type: ignore[arg-type]
    )
    assert result is False


# ── get_supersedes_chain ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_supersedes_chain_single_item(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    item = await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="Standalone"),
    )
    chain = await get_supersedes_chain(conn, item.id)  # type: ignore[arg-type]
    assert len(chain) == 1
    assert chain[0].id == item.id


@pytest.mark.asyncio
async def test_supersedes_chain_three_versions(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    v1 = await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="V1"),
    )
    v2 = await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="V2", supersedes_id=v1.id),
    )
    v3 = await create_item(
        conn,  # type: ignore[arg-type]
        _decision(seed_project, seed_actor, title="V3", supersedes_id=v2.id),
    )

    chain = await get_supersedes_chain(conn, v3.id)  # type: ignore[arg-type]
    assert [i.title for i in chain] == ["V1", "V2", "V3"]


@pytest.mark.asyncio
async def test_supersedes_chain_nonexistent(conn: object) -> None:
    chain = await get_supersedes_chain(conn, "nope")  # type: ignore[arg-type]
    assert chain == []
