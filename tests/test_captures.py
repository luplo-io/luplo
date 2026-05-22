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


async def test_search_captures_matches_text(conn: object) -> None:
    from luplo.core.captures import add_capture, search_captures

    await add_capture(conn, text="family dinner reaction")  # type: ignore[arg-type]
    await add_capture(conn, text="game combat idea")  # type: ignore[arg-type]

    rows = await search_captures(conn, query="family dinner", limit=10)  # type: ignore[arg-type]

    assert [row.text for row in rows] == ["family dinner reaction"]


async def test_set_capture_state_updates_state(conn: object, seed_actor: str) -> None:
    from luplo.core.captures import add_capture, set_capture_state

    capture = await add_capture(conn, text="state target")  # type: ignore[arg-type]
    changed = await set_capture_state(
        conn, capture.id[:8], review_state="backlog", actor_id=seed_actor  # type: ignore[arg-type]
    )

    assert changed.review_state == "backlog"


async def test_discard_capture_hides_from_default_list(conn: object, seed_actor: str) -> None:
    from luplo.core.captures import add_capture, discard_capture, list_captures

    capture = await add_capture(conn, text="discard core target")  # type: ignore[arg-type]
    discarded = await discard_capture(conn, capture.id[:8], actor_id=seed_actor)  # type: ignore[arg-type]

    assert discarded.review_state == "discarded"
    rows = await list_captures(conn, limit=20)  # type: ignore[arg-type]
    assert capture.id not in {row.id for row in rows}


async def test_redact_capture_removes_original_content_from_search(
    conn: object,
    seed_actor: str,
) -> None:
    from luplo.core.captures import add_capture, redact_capture, search_captures

    capture = await add_capture(conn, text="very secret raw phrase")  # type: ignore[arg-type]
    redacted = await redact_capture(conn, capture.id, redacted_by=seed_actor)  # type: ignore[arg-type]

    assert redacted.text == "[redacted]"
    assert redacted.summary == "[redacted]"
    assert redacted.signals == {}
    assert redacted.review_state == "redacted"
    assert redacted.redacted_by == seed_actor

    rows = await search_captures(
        conn, query="very secret raw phrase", include_redacted=True  # type: ignore[arg-type]
    )
    assert rows == []


async def test_local_backend_search_state_discard_and_redact_captures(db_url: str) -> None:
    from luplo.core.backend.local import LocalBackend
    from luplo.core.db import close_pool, create_pool

    actor_id = "00000000-0000-0000-0000-0000000000c4"
    pool = await create_pool(db_url)
    try:
        backend = LocalBackend(pool)
        await backend.create_actor(
            id=actor_id,
            name="Capture Backend Phase2 Actor",
            email="capture-backend-phase2@test.com",
        )
        capture = await backend.add_capture(text="backend secret target", created_by=actor_id)
        found = await backend.search_captures(query="backend secret", limit=10)
        changed = await backend.set_capture_state(
            capture.id[:8], review_state="backlog", actor_id=actor_id
        )
        discarded = await backend.discard_capture(capture.id[:8], actor_id=actor_id)
        listed = await backend.list_captures(limit=10)
        redacted = await backend.redact_capture(capture.id[:8], redacted_by=actor_id)
        after_redact = await backend.search_captures(
            query="backend secret target",
            include_redacted=True,
            limit=10,
        )
    finally:
        await close_pool(pool)

    assert [row.id for row in found] == [capture.id]
    assert changed.review_state == "backlog"
    assert discarded.review_state == "discarded"
    assert capture.id not in {row.id for row in listed}
    assert redacted.text == "[redacted]"
    assert after_redact == []


async def test_annotate_capture_updates_summary_and_signals(conn: object) -> None:
    from luplo.core.captures import add_capture, annotate_capture, search_captures

    capture = await add_capture(conn, text="raw meeting story")  # type: ignore[arg-type]
    updated = await annotate_capture(
        conn,  # type: ignore[arg-type]
        capture.id,
        summary="people issue summary",
        sensitivity_hint="possible",
        signals={"tags": ["people_issue"], "confidence": 0.7},
    )

    assert updated.summary == "people issue summary"
    assert updated.sensitivity_hint == "possible"
    assert updated.signals == {"tags": ["people_issue"], "confidence": 0.7}

    rows = await search_captures(conn, query="people issue summary")  # type: ignore[arg-type]
    assert rows[0].id == capture.id


async def test_annotate_capture_rejects_non_object_signals(conn: object) -> None:
    import pytest

    from luplo.core.captures import add_capture, annotate_capture
    from luplo.core.errors import ValidationError

    capture = await add_capture(conn, text="raw")  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="signals must be a JSON object"):
        await annotate_capture(conn, capture.id, signals=["bad"])  # type: ignore[arg-type]


async def test_local_backend_annotate_capture(db_url: str) -> None:
    from luplo.core.backend.local import LocalBackend
    from luplo.core.db import close_pool, create_pool

    pool = await create_pool(db_url)
    try:
        backend = LocalBackend(pool)
        capture = await backend.add_capture(text="backend annotation target")
        updated = await backend.annotate_capture(
            capture.id[:8],
            summary="backend supplied summary",
            sensitivity_hint="possible",
            signals={"source": "test"},
        )
        found = await backend.search_captures(query="backend supplied summary")
    finally:
        await close_pool(pool)

    assert updated.id == capture.id
    assert updated.summary == "backend supplied summary"
    assert updated.sensitivity_hint == "possible"
    assert updated.signals == {"source": "test"}
    assert [row.id for row in found] == [capture.id]
