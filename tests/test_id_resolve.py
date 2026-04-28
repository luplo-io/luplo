"""Integration tests for core/id_resolve.py.

Covers the helper directly plus the prefix support added to the
``items``, ``tasks``, and ``qa`` getter paths. Runs against a real
PostgreSQL — see ``tests/conftest.py``.
"""

from __future__ import annotations

import uuid

import pytest

from luplo.core.errors import (
    AmbiguousIdError,
    IdTooShortError,
    InvalidIdFormatError,
)
from luplo.core.id_resolve import MIN_PREFIX_LENGTH, resolve_uuid_prefix
from luplo.core.items import create_item, get_item
from luplo.core.models import ItemCreate
from luplo.core.tasks import create_task, get_task

# ── resolve_uuid_prefix ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_uuid_passes_through(conn: object, seed_project: str, seed_actor: str) -> None:
    """A canonical 36-character UUID is returned unchanged."""
    full = "12345678-90ab-cdef-1234-567890abcdef"
    # Even if the row doesn't exist, the function returns ``None`` only
    # after the prefix lookup; full UUIDs short-circuit before any DB
    # call (we still need a valid table reference).
    result = await resolve_uuid_prefix(
        conn,  # type: ignore[arg-type]
        "items",
        full,
    )
    assert result == full


@pytest.mark.asyncio
async def test_prefix_resolves_single_match(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    """A unique 8-char prefix returns the single matching id."""
    item = await create_item(
        conn,  # type: ignore[arg-type]
        ItemCreate(
            project_id=seed_project,
            actor_id=seed_actor,
            item_type="decision",
            title="Resolve me",
        ),
    )
    resolved = await resolve_uuid_prefix(
        conn,  # type: ignore[arg-type]
        "items",
        item.id[:8],
        project_id=seed_project,
    )
    assert resolved == item.id


@pytest.mark.asyncio
async def test_prefix_no_match_returns_none(conn: object, seed_project: str) -> None:
    """A prefix that matches nothing returns ``None``."""
    resolved = await resolve_uuid_prefix(
        conn,  # type: ignore[arg-type]
        "items",
        "deadbeef",
        project_id=seed_project,
    )
    assert resolved is None


@pytest.mark.asyncio
async def test_prefix_ambiguous_raises(conn: object, seed_project: str, seed_actor: str) -> None:
    """Two rows sharing a prefix raise ``AmbiguousIdError``."""
    shared = "abcdef00"
    suffix_a = uuid.uuid4().hex[8:]
    suffix_b = uuid.uuid4().hex[8:]

    def _build(suffix: str) -> str:
        return f"{shared}{suffix[:4]}-{suffix[4:8]}-{suffix[8:12]}-{suffix[12:16]}-{suffix[16:28]}"

    id_a = _build(suffix_a)
    id_b = _build(suffix_b)
    # Insert two items whose ids share the 8-char prefix.
    for forced_id, title in ((id_a, "First"), (id_b, "Second")):
        await conn.execute(  # type: ignore[attr-defined]
            "INSERT INTO items (id, project_id, item_type, title, actor_id) "
            "VALUES (%s, %s, 'decision', %s, %s)",
            (forced_id, seed_project, title, seed_actor),
        )

    with pytest.raises(AmbiguousIdError) as excinfo:
        await resolve_uuid_prefix(
            conn,  # type: ignore[arg-type]
            "items",
            shared,
            project_id=seed_project,
        )
    assert len(excinfo.value.matches) == 2


@pytest.mark.asyncio
async def test_prefix_too_short_raises(conn: object) -> None:
    """A prefix shorter than ``MIN_PREFIX_LENGTH`` is rejected."""
    short = "a" * (MIN_PREFIX_LENGTH - 1)
    with pytest.raises(IdTooShortError):
        await resolve_uuid_prefix(conn, "items", short)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_dashes_are_stripped(conn: object, seed_project: str, seed_actor: str) -> None:
    """Dashes in the input are ignored so users can paste partial UUIDs."""
    item = await create_item(
        conn,  # type: ignore[arg-type]
        ItemCreate(
            project_id=seed_project,
            actor_id=seed_actor,
            item_type="decision",
            title="Dashed prefix",
        ),
    )
    # Insert a dash inside what would otherwise be a 9-char hex prefix —
    # _strip() removes it before validation.
    dashed = f"{item.id[:4]}-{item.id[4:9]}"
    resolved = await resolve_uuid_prefix(
        conn,  # type: ignore[arg-type]
        "items",
        dashed,
        project_id=seed_project,
    )
    assert resolved == item.id


@pytest.mark.asyncio
async def test_non_hex_input_rejected(conn: object) -> None:
    """Inputs containing non-hex characters fail validation."""
    with pytest.raises(InvalidIdFormatError):
        await resolve_uuid_prefix(conn, "items", "zzzzzzzz")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_project_scope_excludes_other_projects(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    """``project_id`` scope hides matches from sibling projects."""
    # Create another project with its own item.
    other_project = "other-project"
    await conn.execute(  # type: ignore[attr-defined]
        "INSERT INTO projects (id, name) VALUES (%s, %s)",
        (other_project, "Other"),
    )
    forced_id = "fa11ed00-0000-4000-8000-000000000000"
    await conn.execute(  # type: ignore[attr-defined]
        "INSERT INTO items (id, project_id, item_type, title, actor_id) "
        "VALUES (%s, %s, 'decision', %s, %s)",
        (forced_id, other_project, "Hidden", seed_actor),
    )

    resolved = await resolve_uuid_prefix(
        conn,  # type: ignore[arg-type]
        "items",
        "fa11ed00",
        project_id=seed_project,  # only matches in seed_project, so misses
    )
    assert resolved is None


# ── Getter integration ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_item_accepts_prefix(conn: object, seed_project: str, seed_actor: str) -> None:
    """``items.get_item`` resolves prefixes end-to-end."""
    item = await create_item(
        conn,  # type: ignore[arg-type]
        ItemCreate(
            project_id=seed_project,
            actor_id=seed_actor,
            item_type="decision",
            title="Prefix lookup",
        ),
    )
    fetched = await get_item(
        conn,  # type: ignore[arg-type]
        item.id[:8],
        project_id=seed_project,
    )
    assert fetched is not None
    assert fetched.id == item.id


@pytest.mark.asyncio
async def test_get_task_accepts_prefix(conn: object, seed_project: str, seed_actor: str) -> None:
    """``tasks.get_task`` resolves prefixes through the supersede CTE."""
    # Open a work unit so we can attach a task.
    from luplo.core.work_units import open_work_unit

    wu = await open_work_unit(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        title="WU for task prefix",
        created_by=seed_actor,
    )
    task = await create_task(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        work_unit_id=wu.id,
        title="Task by prefix",
        actor_id=seed_actor,
    )

    fetched = await get_task(
        conn,  # type: ignore[arg-type]
        task.id[:8],
        project_id=seed_project,
    )
    assert fetched is not None
    assert fetched.id == task.id


# ── Non-UUID ids (page_sync slugs) ─────────────────────────────


@pytest.mark.asyncio
async def test_resolver_accepts_non_uuid_exact_match(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    """page_sync items land with deterministic slug ids; the resolver
    must look them up exactly even though they aren't UUIDs.

    Without the exact-id fast-path, the regex-only check in the legacy
    resolver treated any non-hex character (``j/k/l/w/-`` etc.) as
    ``InvalidIdFormatError`` and the user could never call
    ``luplo_item_show`` on a slugged item.
    """
    slug_id = "cj-knowledge-001-inventorysystem-loading-flow"
    async with conn.cursor() as cur:  # type: ignore[attr-defined]
        await cur.execute(
            "INSERT INTO items (id, project_id, item_type, title, actor_id) "
            "VALUES (%s, %s, %s, %s, %s)",
            (slug_id, seed_project, "knowledge", "Loading Flow", seed_actor),
        )

    resolved = await resolve_uuid_prefix(
        conn,  # type: ignore[arg-type]
        "items",
        slug_id,
        project_id=seed_project,
    )
    assert resolved == slug_id

    fetched = await get_item(
        conn,  # type: ignore[arg-type]
        slug_id,
        project_id=seed_project,
    )
    assert fetched is not None
    assert fetched.id == slug_id


@pytest.mark.asyncio
async def test_resolver_invalid_when_no_exact_and_not_hex(
    conn: object, seed_project: str
) -> None:
    """If no exact row matches and the input isn't a hex prefix either,
    the resolver still raises InvalidIdFormatError — preserves the
    existing not-found-vs-bad-format distinction for callers."""
    with pytest.raises(InvalidIdFormatError):
        await resolve_uuid_prefix(
            conn,  # type: ignore[arg-type]
            "items",
            "definitely-not-a-uuid-or-slug-in-db",
            project_id=seed_project,
        )
