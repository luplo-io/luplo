"""Integration tests for raw text captures."""

from __future__ import annotations


async def test_add_capture_persists_raw_text(conn: object, seed_actor: str) -> None:
    from luplo.core.captures import add_capture, list_captures

    capture = await add_capture(
        conn,  # type: ignore[arg-type]
        text="I felt angry after the meeting.",
        created_by=seed_actor,
    )

    assert capture.text == "I felt angry after the meeting."
    assert capture.review_state == "captured"
    assert capture.sensitivity_hint == "none"
    assert capture.signals == {}
    assert capture.created_by == seed_actor

    rows = await list_captures(conn, limit=10)  # type: ignore[arg-type]
    assert rows[0].id == capture.id


async def test_add_capture_rejects_empty_text(conn: object) -> None:
    import pytest

    from luplo.core.captures import add_capture
    from luplo.core.errors import ValidationError

    with pytest.raises(ValidationError, match="capture text must not be empty"):
        await add_capture(conn, text="   ")  # type: ignore[arg-type]


async def test_list_captures_hides_discarded_and_redacted_by_default(
    conn: object,
    seed_actor: str,
) -> None:
    from luplo.core.captures import add_capture, list_captures

    visible = await add_capture(conn, text="visible", created_by=seed_actor)  # type: ignore[arg-type]
    discarded = await add_capture(
        conn, text="discarded", created_by=seed_actor  # type: ignore[arg-type]
    )
    redacted = await add_capture(conn, text="secret", created_by=seed_actor)  # type: ignore[arg-type]

    await conn.execute(  # type: ignore[attr-defined]
        "UPDATE captures SET review_state = 'discarded' WHERE id = %s",
        (discarded.id,),
    )
    await conn.execute(  # type: ignore[attr-defined]
        "UPDATE captures SET review_state = 'redacted' WHERE id = %s",
        (redacted.id,),
    )

    rows = await list_captures(conn, limit=20)  # type: ignore[arg-type]
    ids = {row.id for row in rows}
    assert visible.id in ids
    assert discarded.id not in ids
    assert redacted.id not in ids


async def test_local_backend_add_and_list_captures(db_url: str) -> None:
    from luplo.core.backend.local import LocalBackend
    from luplo.core.db import close_pool, create_pool

    actor_id = "00000000-0000-0000-0000-0000000000c1"
    pool = await create_pool(db_url)
    try:
        backend = LocalBackend(pool)
        await backend.create_actor(
            id=actor_id,
            name="Capture Backend Actor",
            email="capture-backend@test.com",
        )
        capture = await backend.add_capture(
            text="backend raw note",
            created_by=actor_id,
        )
        rows = await backend.list_captures(limit=10)
    finally:
        await close_pool(pool)

    assert rows[0].id == capture.id
    assert rows[0].text == "backend raw note"
