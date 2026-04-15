"""RemoteBackend — implements the Backend Protocol via HTTP calls.

Used by CLI and MCP server when running in Remote mode (``lp init --remote``).
All operations are forwarded to the luplo HTTP server.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from luplo.core.models import (
    Actor,
    GlossaryGroup,
    GlossaryRejection,
    GlossaryTerm,
    HistoryEntry,
    Item,
    ItemCreate,
    Link,
    Project,
    SearchResult,
    SyncJob,
    System,
    WorkUnit,
)


class RemoteBackend:
    """Backend that delegates to a luplo HTTP server.

    Args:
        base_url: Server URL (e.g. ``https://luplo.mycompany.com``).
        token: Bearer token for authentication.
    """

    def __init__(self, base_url: str, token: str = "") -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"} if token else {},
            timeout=30.0,
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    # ── Projects ─────────────────────────────────────────────────

    async def create_project(
        self, *, id: str, name: str, description: str | None = None
    ) -> Project:
        resp = await self._client.post(
            "/projects", json={"id": id, "name": name, "description": description}
        )
        resp.raise_for_status()
        return _parse_project(resp.json())

    async def get_project(self, id: str) -> Project | None:
        resp = await self._client.get(f"/projects/{id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _parse_project(resp.json())

    async def list_projects(self) -> list[Project]:
        resp = await self._client.get("/projects")
        resp.raise_for_status()
        return [_parse_project(p) for p in resp.json()]

    # ── Items ────────────────────────────────────────────────────

    async def create_item(self, data: ItemCreate) -> Item:
        resp = await self._client.post("/items", json={
            "project_id": data.project_id,
            "item_type": data.item_type,
            "title": data.title,
            "body": data.body,
            "rationale": data.rationale,
            "system_ids": data.system_ids,
            "tags": data.tags,
            "work_unit_id": data.work_unit_id,
            "supersedes_id": data.supersedes_id,
        })
        resp.raise_for_status()
        return _parse_item(resp.json())

    async def get_item(self, id: str) -> Item | None:
        resp = await self._client.get(f"/items/{id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _parse_item(resp.json())

    async def list_items(
        self, project_id: str, *, item_type: str | None = None,
        system_id: str | None = None, work_unit_id: str | None = None,
        include_deleted: bool = False, limit: int = 100, offset: int = 0,
    ) -> list[Item]:
        params: dict[str, Any] = {
            "project_id": project_id, "limit": limit, "offset": offset,
        }
        if item_type:
            params["item_type"] = item_type
        if system_id:
            params["system_id"] = system_id
        if work_unit_id:
            params["work_unit_id"] = work_unit_id
        resp = await self._client.get("/items", params=params)
        resp.raise_for_status()
        return [_parse_item(i) for i in resp.json()]

    async def delete_item(self, id: str, *, actor_id: str) -> None:
        resp = await self._client.delete(f"/items/{id}")
        resp.raise_for_status()

    # ── Search ───────────────────────────────────────────────────

    async def search(
        self, query: str, project_id: str, *,
        item_types: list[str] | None = None,
        system_ids: list[str] | None = None, limit: int = 10,
    ) -> list[SearchResult]:
        params: dict[str, Any] = {
            "q": query, "project_id": project_id, "limit": limit,
        }
        if item_types:
            params["item_types"] = item_types
        if system_ids:
            params["system_ids"] = system_ids
        resp = await self._client.get("/search", params=params)
        resp.raise_for_status()
        return [_parse_search_result(r) for r in resp.json()]

    # ── Work Units ───────────────────────────────────────────────

    async def open_work_unit(
        self, *, id: str, project_id: str, title: str,
        description: str | None = None, system_ids: list[str] | None = None,
        created_by: str | None = None,
    ) -> WorkUnit:
        resp = await self._client.post("/work-units", json={
            "id": id, "project_id": project_id, "title": title,
            "description": description, "system_ids": system_ids or [],
        })
        resp.raise_for_status()
        return _parse_work_unit(resp.json())

    async def close_work_unit(self, id: str, *, actor_id: str) -> WorkUnit:
        resp = await self._client.post(f"/work-units/{id}/close")
        resp.raise_for_status()
        return _parse_work_unit(resp.json())


# ── Parsers ──────────────────────────────────────────────────────


def _parse_project(d: dict[str, Any]) -> Project:
    return Project(
        id=d["id"], name=d["name"], description=d.get("description"),
        created_at=datetime.fromisoformat(d["created_at"]),
    )


def _parse_item(d: dict[str, Any]) -> Item:
    return Item(
        id=d["id"], project_id=d["project_id"], item_type=d["item_type"],
        title=d["title"], body=d.get("body"), source_url=d.get("source_url"),
        parent_item_id=d.get("parent_item_id"),
        work_unit_id=d.get("work_unit_id"), source_ref=d.get("source_ref"),
        actor_id=d.get("actor_id", ""), system_ids=d.get("system_ids", []),
        tags=d.get("tags", []), rationale=d.get("rationale"),
        alternatives=d.get("alternatives"), confidence=d.get("confidence"),
        supersedes_id=d.get("supersedes_id"), deleted_at=None,
        expires_at=None, source_type=d.get("source_type"),
        source_page_id=d.get("source_page_id"),
        stable_section_key=d.get("stable_section_key"),
        current_section_path=d.get("current_section_path"),
        start_anchor=d.get("start_anchor"), content_hash=d.get("content_hash"),
        source_version=d.get("source_version", 1),
        last_synced_at=None,
        created_at=datetime.fromisoformat(d["created_at"]),
        updated_at=datetime.fromisoformat(d["updated_at"]),
    )


def _parse_work_unit(d: dict[str, Any]) -> WorkUnit:
    return WorkUnit(
        id=d["id"], project_id=d["project_id"], title=d["title"],
        description=d.get("description"), system_ids=d.get("system_ids", []),
        status=d["status"], created_by=d.get("created_by"),
        created_at=datetime.fromisoformat(d["created_at"]),
        closed_at=datetime.fromisoformat(d["closed_at"]) if d.get("closed_at") else None,
        closed_by=d.get("closed_by"),
    )


def _parse_search_result(d: dict[str, Any]) -> SearchResult:
    # Minimal item from search response
    item = Item(
        id=d["item_id"], project_id="", item_type=d.get("item_type", ""),
        title=d["title"], body=None, source_url=None, parent_item_id=None,
        work_unit_id=None, source_ref=None, actor_id="",
        system_ids=d.get("system_ids", []), tags=[], rationale=None,
        alternatives=None, confidence=None, supersedes_id=None,
        deleted_at=None, expires_at=None, source_type=None,
        source_page_id=None, stable_section_key=None,
        current_section_path=None, start_anchor=None, content_hash=None,
        source_version=1, last_synced_at=None,
        created_at=datetime.min, updated_at=datetime.min,
    )
    return SearchResult(item=item, score=d.get("score", 0.0), snippet=d.get("snippet"))
