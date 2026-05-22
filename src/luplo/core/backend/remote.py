"""RemoteBackend — implements the Backend Protocol via HTTP calls.

Used by CLI and MCP server when running in Remote mode (``lp init --remote``).
All operations are forwarded to the luplo HTTP server.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from luplo.core.impact import ImpactEdge, ImpactNode, ImpactResult
from luplo.core.models import (
    Capture,
    HistoryEntry,
    Idea,
    Item,
    ItemCreate,
    Project,
    SearchResult,
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
        resp = await self._client.post(
            "/items",
            json={
                "project_id": data.project_id,
                "item_type": data.item_type,
                "title": data.title,
                "body": data.body,
                "rationale": data.rationale,
                "system_ids": data.system_ids,
                "tags": data.tags,
                "work_unit_id": data.work_unit_id,
                "supersedes_id": data.supersedes_id,
                "source_url": data.source_url,
                "expires_at": data.expires_at.isoformat() if data.expires_at else None,
            },
        )
        resp.raise_for_status()
        return _parse_item(resp.json())

    async def get_item(self, id: str, *, project_id: str | None = None) -> Item | None:
        # Remote backend: prefix resolution happens server-side via the
        # route handler; project_id is passed as a query hint when set.
        params: dict[str, str] = {}
        if project_id is not None:
            params["project_id"] = project_id
        resp = await self._client.get(f"/items/{id}", params=params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _parse_item(resp.json())

    async def list_items(
        self,
        project_id: str,
        *,
        item_type: str | None = None,
        system_id: str | None = None,
        work_unit_id: str | None = None,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Item]:
        params: dict[str, Any] = {
            "project_id": project_id,
            "limit": limit,
            "offset": offset,
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

    # ── Impact ───────────────────────────────────────────────────

    async def impact(
        self,
        item_id: str,
        project_id: str,
        *,
        depth: int = 5,
    ) -> ImpactResult:
        resp = await self._client.get(
            f"/items/{item_id}/impact",
            params={"project_id": project_id, "depth": depth},
        )
        resp.raise_for_status()
        return _parse_impact(resp.json())

    # ── Search ───────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        project_id: str,
        *,
        item_types: list[str] | None = None,
        system_ids: list[str] | None = None,
        limit: int = 10,
        tsquery: str | None = None,
    ) -> list[SearchResult]:
        params: dict[str, Any] = {
            "q": query,
            "project_id": project_id,
            "limit": limit,
        }
        if item_types:
            params["item_types"] = item_types
        if system_ids:
            params["system_ids"] = system_ids
        if tsquery is not None:
            params["tsquery"] = tsquery
        resp = await self._client.get("/search", params=params)
        resp.raise_for_status()
        return [_parse_search_result(r) for r in resp.json()]

    # ── Captures (HTTP endpoints land in luplo-saas — stubs for now) ─

    async def add_capture(
        self,
        *,
        text: str,
        created_by: str | None = None,
        summary: str | None = None,
        sensitivity_hint: str = "none",
        signals: dict[str, Any] | None = None,
    ) -> Capture:
        raise NotImplementedError(
            "captures are not yet exposed on the remote backend; use local mode or luplo-cloud"
        )

    async def list_captures(
        self,
        *,
        review_state: str | None = None,
        include_discarded: bool = False,
        include_redacted: bool = False,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[Capture]:
        raise NotImplementedError(
            "captures are not yet exposed on the remote backend; use local mode or luplo-cloud"
        )

    # ── Work Units ───────────────────────────────────────────────

    async def open_work_unit(
        self,
        *,
        id: str,
        project_id: str,
        title: str,
        description: str | None = None,
        system_ids: list[str] | None = None,
        created_by: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> WorkUnit:
        resp = await self._client.post(
            "/work-units",
            json={
                "id": id,
                "project_id": project_id,
                "title": title,
                "description": description,
                "system_ids": system_ids or [],
                "context": context or {},
            },
        )
        resp.raise_for_status()
        return _parse_work_unit(resp.json())

    async def close_work_unit(self, id: str, *, actor_id: str) -> WorkUnit:
        resp = await self._client.post(f"/work-units/{id}/close")
        resp.raise_for_status()
        return _parse_work_unit(resp.json())

    async def archive_work_unit(
        self,
        *,
        id: str,
        archived_by: str,
        replaced_by_wu_id: str,
    ) -> WorkUnit:
        # ``archived_by`` is intentionally NOT sent in the payload — the
        # SaaS server resolves the actor from the bearer token and ignores
        # any client-supplied actor field. We keep the parameter in the
        # signature so the local-mode caller and the protocol stay aligned.
        resp = await self._client.post(
            f"/work-units/{id}/archive",
            json={"replaced_by_wu_id": replaced_by_wu_id},
        )
        if resp.status_code == 404:
            raise ValueError(f"work_unit not found: {id}")
        resp.raise_for_status()
        return _parse_work_unit(resp.json())

    async def find_existing_import_wu(
        self,
        *,
        project_id: str,
        content_hash_set: tuple[str, ...],
    ) -> WorkUnit | None:
        """Look up an existing import work_unit by content hash set.

        Sends ``project_id`` plus a repeated ``content_hash`` query
        parameter (sorted client-side for determinism). 404 maps to
        ``None`` so callers can treat "no match" the same way local
        mode does.
        """
        # httpx accepts a tuple of (key, value) tuples for repeated query
        # keys; the explicit tuple type below appeases pyright's invariant-
        # list complaint while preserving runtime semantics.
        params: tuple[tuple[str, str], ...] = (
            ("project_id", project_id),
            *(("content_hash", h) for h in sorted(content_hash_set)),
        )
        resp = await self._client.get("/work-units/find-existing-import", params=params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _parse_work_unit(resp.json())

    # ── History ──────────────────────────────────────────────────

    async def query_history(
        self,
        *,
        project_id: str | None = None,
        item_id: str | None = None,
        since: datetime | None = None,
        semantic_impacts: list[str] | None = None,
        limit: int = 50,
    ) -> list[HistoryEntry]:
        params: dict[str, Any] = {"limit": limit}
        if project_id is not None:
            params["project_id"] = project_id
        if item_id is not None:
            params["item_id"] = item_id
        if since is not None:
            params["since"] = since.isoformat()
        if semantic_impacts:
            params["semantic_impacts"] = semantic_impacts
        resp = await self._client.get("/history", params=params)
        resp.raise_for_status()
        return [_parse_history_entry(e) for e in resp.json()]

    # ── Ideas (HTTP endpoints land in luplo-saas — stubs for now) ────

    async def add_idea(
        self,
        *,
        project_id: str,
        work_unit_id: str,
        text: str,
        created_by: str | None = None,
    ) -> Idea:
        raise NotImplementedError(
            "ideas are not yet exposed on the remote (cloud) backend; "
            "use local mode (lp init) or wait for the next luplo-cloud release"
        )

    async def list_ideas(
        self,
        *,
        work_unit_id: str,
        project_id: str | None = None,
        limit: int = 100,
        include_redacted: bool = False,
    ) -> list[Idea]:
        raise NotImplementedError("ideas are not yet exposed on the remote (cloud) backend")

    async def search_ideas(
        self,
        *,
        project_id: str,
        query: str | None = None,
        tsquery: str | None = None,
        work_unit_id: str | None = None,
        author: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        include_redacted: bool = False,
        limit: int = 50,
    ) -> list[Idea]:
        raise NotImplementedError("ideas are not yet exposed on the remote (cloud) backend")

    async def get_idea(self, idea_id: str, *, project_id: str | None = None) -> Idea | None:
        raise NotImplementedError("ideas are not yet exposed on the remote (cloud) backend")

    async def redact_idea(
        self,
        *,
        idea_id: str,
        redacted_by: str,
        project_id: str | None = None,
    ) -> tuple[Idea, bool]:
        raise NotImplementedError("ideas are not yet exposed on the remote (cloud) backend")


# ── Parsers ──────────────────────────────────────────────────────


def _parse_project(d: dict[str, Any]) -> Project:
    return Project(
        id=d["id"],
        name=d["name"],
        description=d.get("description"),
        created_at=datetime.fromisoformat(d["created_at"]),
    )


def _parse_item(d: dict[str, Any]) -> Item:
    return Item(
        id=d["id"],
        project_id=d["project_id"],
        item_type=d["item_type"],
        title=d["title"],
        body=d.get("body"),
        source_url=d.get("source_url"),
        parent_item_id=d.get("parent_item_id"),
        work_unit_id=d.get("work_unit_id"),
        source_ref=d.get("source_ref"),
        actor_id=d.get("actor_id", ""),
        system_ids=d.get("system_ids", []),
        tags=d.get("tags", []),
        rationale=d.get("rationale"),
        alternatives=d.get("alternatives"),
        confidence=d.get("confidence"),
        supersedes_id=d.get("supersedes_id"),
        deleted_at=None,
        expires_at=None,
        source_type=d.get("source_type"),
        source_page_id=d.get("source_page_id"),
        stable_section_key=d.get("stable_section_key"),
        current_section_path=d.get("current_section_path"),
        start_anchor=d.get("start_anchor"),
        content_hash=d.get("content_hash"),
        source_version=d.get("source_version", 1),
        last_synced_at=None,
        created_at=datetime.fromisoformat(d["created_at"]),
        updated_at=datetime.fromisoformat(d["updated_at"]),
    )


def _parse_work_unit(d: dict[str, Any]) -> WorkUnit:
    return WorkUnit(
        id=d["id"],
        project_id=d["project_id"],
        title=d["title"],
        description=d.get("description"),
        system_ids=d.get("system_ids", []),
        status=d["status"],
        created_by=d.get("created_by"),
        created_at=datetime.fromisoformat(d["created_at"]),
        closed_at=datetime.fromisoformat(d["closed_at"]) if d.get("closed_at") else None,
        closed_by=d.get("closed_by"),
        context=d.get("context") or {},
    )


def _parse_impact(d: dict[str, Any]) -> ImpactResult:
    root = _parse_item(d["root"])
    nodes: list[ImpactNode] = []
    for n in d.get("nodes", []):
        via_d = n["via"]
        edge = ImpactEdge(
            parent_id=via_d["parent_id"],
            child_id=via_d["child_id"],
            link_type=via_d["link_type"],
            depth=via_d["depth"],
        )
        nodes.append(
            ImpactNode(
                item=_parse_item(n["item"]),
                depth=n["depth"],
                via=edge,
            )
        )
    return ImpactResult(
        root=root,
        nodes=nodes,
        depth_requested=d["depth_requested"],
    )


def _parse_history_entry(d: dict[str, Any]) -> HistoryEntry:
    return HistoryEntry(
        id=d["id"],
        item_id=d["item_id"],
        version=d["version"],
        content_before=d.get("content_before"),
        content_after=d.get("content_after"),
        content_hash_before=d.get("content_hash_before"),
        content_hash_after=d.get("content_hash_after"),
        diff_summary=d.get("diff_summary"),
        semantic_impact=d.get("semantic_impact"),
        changed_at=datetime.fromisoformat(d["changed_at"]),
        changed_by=d["changed_by"],
        source_event_id=d.get("source_event_id"),
        notification_sent=bool(d.get("notification_sent", False)),
    )


def _parse_search_result(d: dict[str, Any]) -> SearchResult:
    # Minimal item from search response
    item = Item(
        id=d["item_id"],
        project_id="",
        item_type=d.get("item_type", ""),
        title=d["title"],
        body=None,
        source_url=None,
        parent_item_id=None,
        work_unit_id=None,
        source_ref=None,
        actor_id="",
        system_ids=d.get("system_ids", []),
        tags=[],
        rationale=None,
        alternatives=None,
        confidence=None,
        supersedes_id=None,
        deleted_at=None,
        expires_at=None,
        source_type=None,
        source_page_id=None,
        stable_section_key=None,
        current_section_path=None,
        start_anchor=None,
        content_hash=None,
        source_version=1,
        last_synced_at=None,
        created_at=datetime.min,
        updated_at=datetime.min,
    )
    return SearchResult(item=item, score=d.get("score", 0.0), snippet=d.get("snippet"))
