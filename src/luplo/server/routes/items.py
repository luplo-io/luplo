"""Item routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from luplo.server.auth.deps import CurrentActor, get_current_actor

router = APIRouter()


class ItemCreateBody(BaseModel):
    project_id: str
    item_type: str = "decision"
    title: str
    body: str | None = None
    rationale: str | None = None
    system_ids: list[str] = []
    tags: list[str] = []
    work_unit_id: str | None = None
    supersedes_id: str | None = None
    source_url: str | None = None
    expires_at: datetime | None = None
    source_type: str | None = None
    source_page_id: str | None = None


def _serialize(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "project_id": item.project_id,
        "item_type": item.item_type,
        "title": item.title,
        "body": item.body,
        "rationale": item.rationale,
        "system_ids": item.system_ids,
        "tags": item.tags,
        "supersedes_id": item.supersedes_id,
        "work_unit_id": item.work_unit_id,
        "source_url": item.source_url,
        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


@router.post("", status_code=201)
async def create_item(
    body: ItemCreateBody,
    request: Request,
    actor: CurrentActor = Depends(get_current_actor),
) -> dict[str, Any]:
    from luplo.core.models import ItemCreate

    b = request.app.state.backend
    item = await b.create_item(
        ItemCreate(
            project_id=body.project_id,
            actor_id=actor.id,
            item_type=body.item_type,
            title=body.title,
            body=body.body,
            rationale=body.rationale,
            system_ids=body.system_ids,
            tags=body.tags,
            work_unit_id=body.work_unit_id,
            supersedes_id=body.supersedes_id,
            source_url=body.source_url,
            expires_at=body.expires_at,
            source_type=body.source_type,
            source_page_id=body.source_page_id,
        )
    )
    return _serialize(item)


@router.get("/{item_id}")
async def get_item(item_id: str, request: Request) -> dict[str, Any]:
    b = request.app.state.backend
    item = await b.get_item(item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    return _serialize(item)


@router.get("")
async def list_items(
    request: Request,
    project_id: str = Query(...),
    item_type: str | None = Query(None),
    system_id: str | None = Query(None),
    work_unit_id: str | None = Query(None),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
) -> list[dict[str, Any]]:
    b = request.app.state.backend
    items = await b.list_items(
        project_id,
        item_type=item_type,
        system_id=system_id,
        work_unit_id=work_unit_id,
        limit=limit,
        offset=offset,
    )
    return [_serialize(i) for i in items]


@router.delete("/{item_id}", status_code=204)
async def delete_item(
    item_id: str,
    request: Request,
    actor: CurrentActor = Depends(get_current_actor),
) -> None:
    b = request.app.state.backend
    await b.delete_item(item_id, actor_id=actor.id)
