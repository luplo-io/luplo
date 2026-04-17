"""Search route."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

router = APIRouter()


@router.get("")
async def search_items(
    request: Request,
    q: str = Query(..., description="Search query"),
    project_id: str = Query(...),
    item_types: list[str] | None = Query(None),
    system_ids: list[str] | None = Query(None),
    limit: int = Query(10, le=50),
) -> list[dict[str, Any]]:
    """Full-text search with glossary expansion."""
    b = request.app.state.backend
    results = await b.search(
        q,
        project_id,
        item_types=item_types,
        system_ids=system_ids,
        limit=limit,
    )
    return [
        {
            "item_id": r.item.id,
            "title": r.item.title,
            "item_type": r.item.item_type,
            "score": r.score,
            "snippet": r.snippet,
            "system_ids": r.item.system_ids,
        }
        for r in results
    ]
