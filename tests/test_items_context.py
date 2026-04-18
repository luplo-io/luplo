"""Tests for items.context — the JSONB free-form column added in 0003."""

from __future__ import annotations

import pytest

from luplo.core.errors import ContextValidationError, UnknownItemTypeError
from luplo.core.items import create_item, get_item, list_items
from luplo.core.models import ItemCreate


@pytest.mark.asyncio
async def test_create_item_default_context_is_empty(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    item = await create_item(
        conn,  # type: ignore[arg-type]
        ItemCreate(
            project_id=seed_project,
            actor_id=seed_actor,
            item_type="decision",
            title="No context",
        ),
    )
    assert item.context == {}


@pytest.mark.asyncio
async def test_create_item_with_context_round_trip(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    payload = {"freeform": "value", "nested": {"k": 1}}
    item = await create_item(
        conn,  # type: ignore[arg-type]
        ItemCreate(
            project_id=seed_project,
            actor_id=seed_actor,
            item_type="decision",
            title="Loose",
            context=payload,
        ),
    )
    assert item.context == payload

    fetched = await get_item(conn, item.id)  # type: ignore[arg-type]
    assert fetched is not None
    assert fetched.context == payload


@pytest.mark.asyncio
async def test_create_item_task_context_validates(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    item = await create_item(
        conn,  # type: ignore[arg-type]
        ItemCreate(
            project_id=seed_project,
            actor_id=seed_actor,
            item_type="task",
            title="A task",
            context={"status": "proposed", "sort_order": 10},
        ),
    )
    assert item.context["status"] == "proposed"
    assert item.context["sort_order"] == 10


@pytest.mark.asyncio
async def test_create_item_task_missing_required_status(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    with pytest.raises(ContextValidationError):
        await create_item(
            conn,  # type: ignore[arg-type]
            ItemCreate(
                project_id=seed_project,
                actor_id=seed_actor,
                item_type="task",
                title="Bad task — no status",
                context={"sort_order": 10},
            ),
        )


@pytest.mark.asyncio
async def test_create_item_task_extra_field_rejected(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    with pytest.raises(ContextValidationError):
        await create_item(
            conn,  # type: ignore[arg-type]
            ItemCreate(
                project_id=seed_project,
                actor_id=seed_actor,
                item_type="task",
                title="Bad task — extra field",
                context={"status": "proposed", "not_in_schema": True},
            ),
        )


@pytest.mark.asyncio
async def test_create_item_unknown_type_rejected(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    with pytest.raises(UnknownItemTypeError):
        await create_item(
            conn,  # type: ignore[arg-type]
            ItemCreate(
                project_id=seed_project,
                actor_id=seed_actor,
                item_type="no_such_type",
                title="Bad type",
            ),
        )


@pytest.mark.asyncio
async def test_list_items_returns_context(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    await create_item(
        conn,  # type: ignore[arg-type]
        ItemCreate(
            project_id=seed_project,
            actor_id=seed_actor,
            item_type="knowledge",
            title="With context",
            context={"source_url_extra": "http://example.com/foo"},
        ),
    )
    rows = await list_items(  # type: ignore[arg-type]
        conn, seed_project, item_type="knowledge"
    )
    assert any(r.context.get("source_url_extra") for r in rows)
