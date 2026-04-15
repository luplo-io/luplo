"""Smoke tests for LocalBackend — verify wiring through the full stack.

These tests use a real connection pool (not the per-test rollback conn),
so each test cleans up after itself.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from psycopg_pool import AsyncConnectionPool

from luplo.core.backend.local import LocalBackend
from luplo.core.models import ItemCreate


@pytest_asyncio.fixture
async def backend(db_url: str) -> LocalBackend:
    """Create a LocalBackend with a real connection pool."""
    pool = AsyncConnectionPool(db_url, min_size=1, max_size=2, open=False)
    await pool.open()
    try:
        yield LocalBackend(pool)  # type: ignore[misc]
    finally:
        await pool.close()


def _uid() -> str:
    return str(uuid.uuid4())


@pytest.mark.asyncio
async def test_project_lifecycle(backend: LocalBackend) -> None:
    pid = _uid()
    p = await backend.create_project(id=pid, name=f"test-{pid[:8]}")
    assert p.id == pid

    fetched = await backend.get_project(pid)
    assert fetched is not None
    assert fetched.name == p.name

    all_projects = await backend.list_projects()
    assert any(pp.id == pid for pp in all_projects)


@pytest.mark.asyncio
async def test_actor_lifecycle(backend: LocalBackend) -> None:
    aid = _uid()
    a = await backend.create_actor(id=aid, name="Test Actor", email=f"{aid[:8]}@test.com")
    assert a.id == aid

    fetched = await backend.get_actor(aid)
    assert fetched is not None

    by_email = await backend.get_actor_by_email(f"{aid[:8]}@test.com")
    assert by_email is not None
    assert by_email.id == aid


@pytest.mark.asyncio
async def test_item_crud_with_audit(backend: LocalBackend) -> None:
    pid = _uid()
    aid = _uid()
    await backend.create_project(id=pid, name=f"proj-{pid[:8]}")
    await backend.create_actor(id=aid, name="Actor")

    item = await backend.create_item(
        ItemCreate(project_id=pid, actor_id=aid, item_type="decision", title="Test decision")
    )
    assert item.id is not None

    fetched = await backend.get_item(item.id)
    assert fetched is not None
    assert fetched.title == "Test decision"

    # Soft delete
    await backend.delete_item(item.id, actor_id=aid)
    assert await backend.get_item(item.id) is None


@pytest.mark.asyncio
async def test_item_supersede_creates_history(backend: LocalBackend) -> None:
    pid = _uid()
    aid = _uid()
    await backend.create_project(id=pid, name=f"proj-{pid[:8]}")
    await backend.create_actor(id=aid, name="Actor")

    v1 = await backend.create_item(
        ItemCreate(
            project_id=pid, actor_id=aid, item_type="decision",
            title="V1", body="Original",
        )
    )
    v2 = await backend.create_item(
        ItemCreate(
            project_id=pid, actor_id=aid, item_type="decision",
            title="V2", body="Updated", supersedes_id=v1.id,
        )
    )

    # History should record the supersede
    entries = await backend.query_history(item_id=v2.id)
    assert len(entries) >= 1
    assert entries[0].content_before == "Original"
    assert entries[0].content_after == "Updated"


@pytest.mark.asyncio
async def test_work_unit_lifecycle(backend: LocalBackend) -> None:
    pid = _uid()
    aid = _uid()
    await backend.create_project(id=pid, name=f"proj-{pid[:8]}")
    await backend.create_actor(id=aid, name="Actor")

    wu = await backend.open_work_unit(
        id=_uid(), project_id=pid, title="Design sprint", created_by=aid,
    )
    assert wu.status == "in_progress"

    active = await backend.list_work_units(pid, status="in_progress")
    assert any(w.id == wu.id for w in active)

    closed = await backend.close_work_unit(wu.id, actor_id=aid)
    assert closed.status == "done"


@pytest.mark.asyncio
async def test_search_through_backend(backend: LocalBackend) -> None:
    pid = _uid()
    aid = _uid()
    await backend.create_project(id=pid, name=f"proj-{pid[:8]}")
    await backend.create_actor(id=aid, name="Actor")

    await backend.create_item(
        ItemCreate(
            project_id=pid, actor_id=aid, item_type="decision",
            title="Vendor budget formula", body="NPC shops use goldpool",
        )
    )

    results = await backend.search("vendor", pid)
    assert len(results) >= 1
    assert results[0].item.title == "Vendor budget formula"


@pytest.mark.asyncio
async def test_glossary_through_backend(backend: LocalBackend) -> None:
    pid = _uid()
    aid = _uid()
    gid = _uid()
    await backend.create_project(id=pid, name=f"proj-{pid[:8]}")
    await backend.create_actor(id=aid, name="Actor")

    group = await backend.create_glossary_group(
        id=gid, project_id=pid, canonical="vendor",
    )
    assert group.canonical == "vendor"

    term = await backend.create_glossary_term(
        id=_uid(), group_id=gid, surface="shop",
        normalized="shop", status="pending",
    )

    pending = await backend.list_pending_terms(pid)
    assert any(t.id == term.id for t in pending)

    approved = await backend.approve_term(
        term.id, group_id=gid, actor_id=aid,
    )
    assert approved.status == "alias"


@pytest.mark.asyncio
async def test_sync_through_backend(backend: LocalBackend) -> None:
    job = await backend.enqueue_sync(
        source_type="notion", source_page_id="page-1",
        payload="# Content", debounce_seconds=0,
    )
    assert job.status == "pending"

    ready = await backend.get_ready_sync_jobs(limit=1)
    assert len(ready) == 1

    await backend.complete_sync_job(ready[0].id)


@pytest.mark.asyncio
async def test_link_through_backend(backend: LocalBackend) -> None:
    pid = _uid()
    aid = _uid()
    await backend.create_project(id=pid, name=f"proj-{pid[:8]}")
    await backend.create_actor(id=aid, name="Actor")

    a = await backend.create_item(
        ItemCreate(project_id=pid, actor_id=aid, item_type="decision", title="A")
    )
    b = await backend.create_item(
        ItemCreate(project_id=pid, actor_id=aid, item_type="decision", title="B")
    )

    link = await backend.create_link(
        from_item_id=a.id, to_item_id=b.id, link_type="excludes", actor_id=aid,
    )
    assert link.link_type == "excludes"

    found = await backend.get_links(a.id, direction="from")
    assert len(found) == 1
