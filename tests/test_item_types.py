"""Tests for the item_types registry (Phase C)."""

from __future__ import annotations

import pytest

from luplo.core.item_types import (
    ContextValidationError,
    UnknownItemTypeError,
    create_item_type,
    get_item_type,
    invalidate_cache,
    list_item_types,
    validate_context,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Reset the in-memory schema cache between tests."""
    invalidate_cache()


@pytest.mark.asyncio
async def test_seeded_types_present(conn: object) -> None:
    rows = await list_item_types(conn)  # type: ignore[arg-type]
    keys = {r.key for r in rows}
    assert {"decision", "knowledge", "policy", "document", "task", "qa_check"} <= keys
    for r in rows:
        if r.key in {"task", "qa_check"}:
            assert r.schema.get("additionalProperties") is False
        else:
            assert r.schema.get("additionalProperties") is True


@pytest.mark.asyncio
async def test_get_item_type_found(conn: object) -> None:
    t = await get_item_type(conn, "task")  # type: ignore[arg-type]
    assert t is not None
    assert t.owner == "system"
    assert "status" in t.schema["properties"]


@pytest.mark.asyncio
async def test_get_item_type_missing(conn: object) -> None:
    assert await get_item_type(conn, "no_such_type") is None  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_validate_context_decision_loose(conn: object) -> None:
    # decision schema accepts arbitrary properties (P6).
    await validate_context(
        conn,  # type: ignore[arg-type]
        "decision",
        {"any_field": "any value", "more": [1, 2, 3]},
    )


@pytest.mark.asyncio
async def test_validate_context_task_strict_passes(conn: object) -> None:
    await validate_context(
        conn,  # type: ignore[arg-type]
        "task",
        {"status": "proposed", "sort_order": 10, "systems": ["a"]},
    )


@pytest.mark.asyncio
async def test_validate_context_task_missing_required(conn: object) -> None:
    with pytest.raises(ContextValidationError) as exc:
        await validate_context(
            conn,  # type: ignore[arg-type]
            "task",
            {"sort_order": 10},  # missing required "status"
        )
    assert "status" in str(exc.value)


@pytest.mark.asyncio
async def test_validate_context_task_extra_field_rejected(conn: object) -> None:
    with pytest.raises(ContextValidationError):
        await validate_context(
            conn,  # type: ignore[arg-type]
            "task",
            {"status": "proposed", "unknown_field": True},
        )


@pytest.mark.asyncio
async def test_validate_context_task_bad_status_enum(conn: object) -> None:
    with pytest.raises(ContextValidationError) as exc:
        await validate_context(
            conn,  # type: ignore[arg-type]
            "task",
            {"status": "not_a_valid_status"},
        )
    assert "status" in str(exc.value)


@pytest.mark.asyncio
async def test_validate_context_unknown_type(conn: object) -> None:
    with pytest.raises(UnknownItemTypeError):
        await validate_context(
            conn,  # type: ignore[arg-type]
            "no_such_type",
            {},
        )


@pytest.mark.asyncio
async def test_validate_context_qa_check_strict(conn: object) -> None:
    await validate_context(
        conn,  # type: ignore[arg-type]
        "qa_check",
        {
            "status": "pending",
            "coverage": "human_only",
            "areas": ["vfx", "edge_case"],
            "target_task_ids": ["00000000-0000-0000-0000-000000000001"],
        },
    )

    with pytest.raises(ContextValidationError):
        await validate_context(
            conn,  # type: ignore[arg-type]
            "qa_check",
            {"status": "pending"},  # missing required coverage
        )


@pytest.mark.asyncio
async def test_create_user_item_type(conn: object) -> None:
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {"team": {"type": "string"}},
        "required": ["team"],
        "additionalProperties": False,
    }
    t = await create_item_type(
        conn,  # type: ignore[arg-type]
        key="sprint",
        display_name="Sprint",
        schema=schema,
        owner="user",
    )
    assert t.owner == "user"
    assert t.schema == schema

    # Round-trip: validation honours the freshly registered schema.
    await validate_context(
        conn, "sprint", {"team": "alpha"}  # type: ignore[arg-type]
    )
    with pytest.raises(ContextValidationError):
        await validate_context(
            conn, "sprint", {}  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_create_user_item_type_invalid_schema(conn: object) -> None:
    bad_schema = {"type": "no_such_type"}  # not a valid JSON Schema type
    with pytest.raises(ContextValidationError):
        await create_item_type(
            conn,  # type: ignore[arg-type]
            key="bad_schema_type",
            display_name="bad",
            schema=bad_schema,
            owner="user",
        )
