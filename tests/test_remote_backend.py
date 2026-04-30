"""Unit tests for RemoteBackend using httpx.MockTransport.

Each test wires a mock transport that inspects the request path/method/
body and returns a canned JSON response. The backend's HTTP client is
replaced after construction so all requests hit the mock.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from luplo.core.backend.remote import RemoteBackend
from luplo.core.models import ItemCreate


def _iso(dt: datetime) -> str:
    return dt.isoformat()


_NOW = datetime(2026, 4, 17, tzinfo=UTC)


def _make_backend(handler: httpx.MockTransport) -> RemoteBackend:
    b = RemoteBackend("https://luplo.example", token="test-token")
    # Replace the real client with one that routes to the mock.
    original = b._client
    b._client = httpx.AsyncClient(
        base_url=original.base_url,
        headers=original.headers,
        transport=handler,
        timeout=5.0,
    )
    # Close the original (never used) to avoid a resource warning.
    # Note: AsyncClient.aclose() is async; we drop the reference instead.
    del original
    return b


def _project_payload(pid: str) -> dict[str, Any]:
    return {
        "id": pid,
        "name": pid,
        "description": None,
        "created_at": _iso(_NOW),
    }


def _item_payload(iid: str, project_id: str, title: str = "t") -> dict[str, Any]:
    return {
        "id": iid,
        "project_id": project_id,
        "item_type": "decision",
        "title": title,
        "body": None,
        "source_url": None,
        "parent_item_id": None,
        "work_unit_id": None,
        "source_ref": None,
        "actor_id": "actor-1",
        "system_ids": [],
        "tags": [],
        "rationale": None,
        "alternatives": None,
        "confidence": None,
        "supersedes_id": None,
        "deleted_at": None,
        "expires_at": None,
        "source_type": None,
        "source_page_id": None,
        "stable_section_key": None,
        "current_section_path": None,
        "start_anchor": None,
        "content_hash": None,
        "source_version": 1,
        "last_synced_at": None,
        "created_at": _iso(_NOW),
        "updated_at": _iso(_NOW),
    }


def _wu_payload(wid: str, project_id: str, title: str) -> dict[str, Any]:
    return {
        "id": wid,
        "project_id": project_id,
        "title": title,
        "description": None,
        "system_ids": [],
        "status": "in_progress",
        "created_by": "actor-1",
        "created_at": _iso(_NOW),
        "closed_at": None,
        "closed_by": None,
    }


# ── Projects ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_project() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/projects"
        body = json.loads(request.content)
        assert body["id"] == "p1"
        return httpx.Response(201, json=_project_payload("p1"))

    b = _make_backend(httpx.MockTransport(handle))
    proj = await b.create_project(id="p1", name="p1")
    assert proj.id == "p1"
    await b.close()


@pytest.mark.asyncio
async def test_get_project_found() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/projects/p2"
        return httpx.Response(200, json=_project_payload("p2"))

    b = _make_backend(httpx.MockTransport(handle))
    proj = await b.get_project("p2")
    assert proj and proj.id == "p2"
    await b.close()


@pytest.mark.asyncio
async def test_get_project_missing() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "not found"})

    b = _make_backend(httpx.MockTransport(handle))
    assert await b.get_project("nope") is None
    await b.close()


@pytest.mark.asyncio
async def test_list_projects() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_project_payload("a"), _project_payload("b")])

    b = _make_backend(httpx.MockTransport(handle))
    rows = await b.list_projects()
    assert [p.id for p in rows] == ["a", "b"]
    await b.close()


# ── Items ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_item_serializes_fields() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/items"
        body = json.loads(request.content)
        assert body["title"] == "Hello"
        assert body["expires_at"] == _iso(_NOW)
        return httpx.Response(201, json=_item_payload("i1", "p1", "Hello"))

    b = _make_backend(httpx.MockTransport(handle))
    created = await b.create_item(
        ItemCreate(
            project_id="p1",
            actor_id="a1",
            item_type="decision",
            title="Hello",
            expires_at=_NOW,
        )
    )
    assert created.title == "Hello"
    await b.close()


@pytest.mark.asyncio
async def test_get_item_with_project_param() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/items/i2"
        assert request.url.params.get("project_id") == "p1"
        return httpx.Response(200, json=_item_payload("i2", "p1"))

    b = _make_backend(httpx.MockTransport(handle))
    item = await b.get_item("i2", project_id="p1")
    assert item and item.id == "i2"
    await b.close()


@pytest.mark.asyncio
async def test_get_item_missing() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    b = _make_backend(httpx.MockTransport(handle))
    assert await b.get_item("iX") is None
    await b.close()


@pytest.mark.asyncio
async def test_list_items_with_filters() -> None:
    captured: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = str(request.url.params)
        return httpx.Response(200, json=[_item_payload("i1", "p1")])

    b = _make_backend(httpx.MockTransport(handle))
    rows = await b.list_items(
        "p1",
        item_type="decision",
        system_id="s1",
        work_unit_id="w1",
        limit=10,
    )
    assert len(rows) == 1
    assert "item_type=decision" in captured["params"]
    assert "system_id=s1" in captured["params"]
    assert "work_unit_id=w1" in captured["params"]
    await b.close()


@pytest.mark.asyncio
async def test_delete_item() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        return httpx.Response(204)

    b = _make_backend(httpx.MockTransport(handle))
    await b.delete_item("i1", actor_id="a1")
    await b.close()


# ── Impact ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_impact_parses_nested_payload() -> None:
    payload = {
        "root": _item_payload("root1", "p1", "root"),
        "nodes": [
            {
                "item": _item_payload("child1", "p1", "child"),
                "depth": 1,
                "via": {
                    "parent_id": "root1",
                    "child_id": "child1",
                    "link_type": "depends",
                    "depth": 1,
                },
            }
        ],
        "depth_requested": 3,
    }

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/items/root1/impact"
        return httpx.Response(200, json=payload)

    b = _make_backend(httpx.MockTransport(handle))
    result = await b.impact("root1", "p1", depth=3)
    assert result.root.id == "root1"
    assert len(result.nodes) == 1
    assert result.nodes[0].via.link_type == "depends"
    await b.close()


# ── Search ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_with_filters() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        params = str(request.url.params)
        assert "q=vendor" in params
        assert "item_types=decision" in params
        assert "system_ids=s1" in params
        return httpx.Response(
            200,
            json=[
                {
                    "item_id": "i1",
                    "title": "Vendor rule",
                    "score": 0.87,
                    "snippet": "...",
                    "item_type": "decision",
                    "system_ids": ["s1"],
                }
            ],
        )

    b = _make_backend(httpx.MockTransport(handle))
    rows = await b.search(
        "vendor",
        "p1",
        item_types=["decision"],
        system_ids=["s1"],
        limit=5,
    )
    assert len(rows) == 1
    assert rows[0].item.title == "Vendor rule"
    assert rows[0].score == 0.87
    await b.close()


@pytest.mark.asyncio
async def test_search_no_filters() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    b = _make_backend(httpx.MockTransport(handle))
    assert await b.search("q", "p1") == []
    await b.close()


# ── Work units ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_work_unit() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/work-units"
        body = json.loads(request.content)
        assert body["title"] == "Sprint"
        return httpx.Response(201, json=_wu_payload("w1", "p1", "Sprint"))

    b = _make_backend(httpx.MockTransport(handle))
    wu = await b.open_work_unit(id="w1", project_id="p1", title="Sprint", system_ids=["s1"])
    assert wu.title == "Sprint"
    await b.close()


@pytest.mark.asyncio
async def test_close_work_unit() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/work-units/w1/close"
        closed = _wu_payload("w1", "p1", "Sprint")
        closed["status"] = "done"
        closed["closed_at"] = _iso(_NOW)
        closed["closed_by"] = "a1"
        return httpx.Response(200, json=closed)

    b = _make_backend(httpx.MockTransport(handle))
    wu = await b.close_work_unit("w1", actor_id="a1")
    assert wu.status == "done"
    await b.close()


@pytest.mark.asyncio
async def test_archive_work_unit_returns_archived_wu() -> None:
    """200 path: server returns the archived WorkUnit JSON."""

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/work-units/w1/archive"
        # Body must NOT carry actor_id — server resolves caller from token.
        body = request.read().decode()
        assert "archived_by" not in body
        assert "replaced_by_wu_id" in body
        wu = _wu_payload("w1", "p1", "Old WU")
        wu["status"] = "archived"
        wu["closed_at"] = _iso(_NOW)
        wu["closed_by"] = "a1"
        wu["context"] = {"replaced_by": "w2"}
        return httpx.Response(200, json=wu)

    b = _make_backend(httpx.MockTransport(handle))
    archived = await b.archive_work_unit(id="w1", archived_by="a1", replaced_by_wu_id="w2")
    assert archived.status == "archived"
    assert archived.context.get("replaced_by") == "w2"
    await b.close()


@pytest.mark.asyncio
async def test_archive_work_unit_404_raises_value_error() -> None:
    """404 = wu_id not found; mirrors LocalBackend's ValueError contract."""

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/work-units/ghost/archive"
        return httpx.Response(404, json={"detail": "not found"})

    b = _make_backend(httpx.MockTransport(handle))
    with pytest.raises(ValueError, match="work_unit not found"):
        await b.archive_work_unit(id="ghost", archived_by="a1", replaced_by_wu_id="w2")
    await b.close()


@pytest.mark.asyncio
async def test_find_existing_import_wu_match() -> None:
    """200 path: server returns the matching import work_unit."""

    seen_params: list[tuple[str, str]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/work-units/find-existing-import"
        seen_params.extend(request.url.params.multi_items())
        return httpx.Response(200, json=_wu_payload("wu-import", "p1", "Import bundle"))

    b = _make_backend(httpx.MockTransport(handle))
    result = await b.find_existing_import_wu(
        project_id="p1", content_hash_set=("hash-b", "hash-a")
    )
    assert result is not None
    assert result.id == "wu-import"
    # Hashes are sorted on the wire so the server can index lookups deterministically.
    hash_params = [v for k, v in seen_params if k == "content_hash"]
    assert hash_params == sorted(hash_params)
    assert ("project_id", "p1") in seen_params
    await b.close()


@pytest.mark.asyncio
async def test_find_existing_import_wu_404_returns_none() -> None:
    """404 = no matching bundle; mirror LocalBackend's None return."""

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/work-units/find-existing-import"
        return httpx.Response(404, json={"detail": "not found"})

    b = _make_backend(httpx.MockTransport(handle))
    result = await b.find_existing_import_wu(project_id="p1", content_hash_set=("h",))
    assert result is None
    await b.close()


# ── History ─────────────────────────────────────────────────────


def _history_payload(item_id: str = "i1", version: int = 1) -> dict[str, Any]:
    return {
        "id": 99,
        "item_id": item_id,
        "version": version,
        "content_before": None,
        "content_after": "hello",
        "content_hash_before": None,
        "content_hash_after": "deadbeef",
        "diff_summary": "added body",
        "semantic_impact": None,
        "changed_at": _iso(_NOW),
        "changed_by": "actor-1",
        "source_event_id": None,
        "notification_sent": False,
    }


@pytest.mark.asyncio
async def test_query_history_minimal() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/history"
        params = dict(request.url.params)
        assert params == {"limit": "50", "project_id": "p1"}
        return httpx.Response(200, json=[_history_payload()])

    b = _make_backend(httpx.MockTransport(handle))
    rows = await b.query_history(project_id="p1")
    assert len(rows) == 1
    assert rows[0].item_id == "i1"
    assert rows[0].version == 1
    assert rows[0].changed_at == _NOW
    await b.close()


@pytest.mark.asyncio
async def test_query_history_filters_passed_through() -> None:
    """item_id, since, semantic_impacts, limit all forwarded as query params."""
    seen: dict[str, Any] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params.multi_items())
        return httpx.Response(200, json=[])

    b = _make_backend(httpx.MockTransport(handle))
    await b.query_history(
        project_id="p1",
        item_id="i1",
        since=_NOW,
        semantic_impacts=["body_changed"],
        limit=10,
    )
    assert seen.get("project_id") == "p1"
    assert seen.get("item_id") == "i1"
    assert seen.get("since") == _iso(_NOW)
    assert seen.get("limit") == "10"
    await b.close()


@pytest.mark.asyncio
async def test_query_history_empty() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    b = _make_backend(httpx.MockTransport(handle))
    assert await b.query_history(project_id="p1") == []
    await b.close()


# ── Constructor ─────────────────────────────────────────────────


def test_constructor_without_token() -> None:
    """No token → no Authorization header."""
    b = RemoteBackend("https://luplo.example")
    assert "authorization" not in {k.lower() for k in b._client.headers}


def test_constructor_strips_trailing_slash() -> None:
    b = RemoteBackend("https://luplo.example/", token="t")
    assert str(b._client.base_url) == "https://luplo.example"
