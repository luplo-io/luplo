"""Integration tests for the FastAPI server."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

# Attribution actor UUID sent via the X-Actor header on every write.
_TEST_SERVER_ACTOR_UUID = "00000000-0000-0000-0000-0000000000ab"
_ACTOR_HEADERS = {"X-Actor": _TEST_SERVER_ACTOR_UUID}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def db_url_env(db_url: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """Set LUPLO_DB_URL for the server."""
    monkeypatch.setenv("LUPLO_DB_URL", db_url)
    return db_url


@pytest.fixture
async def client(db_url_env: str) -> AsyncClient:  # type: ignore[misc]
    """Create an async test client with manually initialised backend.

    Writes send ``X-Actor`` in ``_ACTOR_HEADERS`` to attribute the request.
    """
    from luplo.core.backend.local import LocalBackend
    from luplo.core.db import close_pool, create_pool
    from luplo.server.app import app
    from luplo.server.config import load_settings

    pool = await create_pool(db_url_env)
    app.state.backend = LocalBackend(pool)
    app.state.pool = pool
    app.state.settings = load_settings()

    # Seed the actor stamped on every write via X-Actor.
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO actors (id, name, email) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (_TEST_SERVER_ACTOR_UUID, "Test Server Actor", "test-server@luplo.io"),
        )

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c  # type: ignore[misc]

    await close_pool(pool)


def _uid() -> str:
    return str(uuid.uuid4())


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_project_crud(client: AsyncClient) -> None:
    pid = _uid()
    # Create
    resp = await client.post(
        "/projects",
        json={"id": pid, "name": f"test-{pid[:8]}"},
        headers=_ACTOR_HEADERS,
    )
    assert resp.status_code == 201
    assert resp.json()["id"] == pid

    # Get
    resp = await client.get(f"/projects/{pid}")
    assert resp.status_code == 200
    assert resp.json()["name"] == f"test-{pid[:8]}"

    # List
    resp = await client.get("/projects")
    assert resp.status_code == 200
    assert any(p["id"] == pid for p in resp.json())


@pytest.mark.asyncio
async def test_project_not_found(client: AsyncClient) -> None:
    resp = await client.get("/projects/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_item_crud(client: AsyncClient) -> None:
    pid = _uid()
    await client.post(
        "/projects",
        json={"id": pid, "name": f"proj-{pid[:8]}"},
        headers=_ACTOR_HEADERS,
    )

    # Create item
    resp = await client.post(
        "/items",
        json={
            "project_id": pid,
            "title": "Test decision",
            "item_type": "decision",
        },
        headers=_ACTOR_HEADERS,
    )
    assert resp.status_code == 201
    item_id = resp.json()["id"]

    # Get
    resp = await client.get(f"/items/{item_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Test decision"

    # List
    resp = await client.get("/items", params={"project_id": pid})
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    # Delete (soft)
    resp = await client.delete(f"/items/{item_id}", headers=_ACTOR_HEADERS)
    assert resp.status_code == 204

    # Get after delete
    resp = await client.get(f"/items/{item_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_work_unit_lifecycle(client: AsyncClient) -> None:
    pid = _uid()
    wid = _uid()
    await client.post(
        "/projects",
        json={"id": pid, "name": f"proj-{pid[:8]}"},
        headers=_ACTOR_HEADERS,
    )

    # Open
    resp = await client.post(
        "/work-units",
        json={
            "id": wid,
            "project_id": pid,
            "title": "Sprint 1",
        },
        headers=_ACTOR_HEADERS,
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "in_progress"

    # List
    resp = await client.get("/work-units", params={"project_id": pid})
    assert len(resp.json()) >= 1

    # Close
    resp = await client.post(f"/work-units/{wid}/close", headers=_ACTOR_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"


@pytest.mark.asyncio
async def test_search(client: AsyncClient) -> None:
    pid = _uid()
    await client.post(
        "/projects",
        json={"id": pid, "name": f"proj-{pid[:8]}"},
        headers=_ACTOR_HEADERS,
    )

    await client.post(
        "/items",
        json={
            "project_id": pid,
            "title": "Vendor budget formula",
            "body": "NPC shops use goldpool percentage",
            "item_type": "decision",
        },
        headers=_ACTOR_HEADERS,
    )

    resp = await client.get("/search", params={"q": "vendor", "project_id": pid})
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) >= 1
    assert "vendor" in results[0]["title"].lower()


@pytest.mark.asyncio
async def test_write_without_actor_header_rejected(client: AsyncClient) -> None:
    pid = _uid()
    resp = await client.post("/projects", json={"id": pid, "name": f"noactor-{pid[:8]}"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_ready(client: AsyncClient) -> None:
    resp = await client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"
