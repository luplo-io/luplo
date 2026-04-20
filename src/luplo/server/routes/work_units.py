"""Work unit routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from luplo.server.deps import require_actor_id

router = APIRouter()


class WorkUnitCreateBody(BaseModel):
    id: str
    project_id: str
    title: str
    description: str | None = None
    system_ids: list[str] = []


class WorkUnitCloseBody(BaseModel):
    status: str = "done"


def _serialize(wu: Any) -> dict[str, Any]:
    return {
        "id": wu.id,
        "project_id": wu.project_id,
        "title": wu.title,
        "description": wu.description,
        "system_ids": wu.system_ids,
        "status": wu.status,
        "created_by": wu.created_by,
        "created_at": wu.created_at.isoformat(),
        "closed_at": wu.closed_at.isoformat() if wu.closed_at else None,
        "closed_by": wu.closed_by,
    }


@router.post("", status_code=201)
async def open_work_unit(
    body: WorkUnitCreateBody,
    request: Request,
    actor_id: str = Depends(require_actor_id),
) -> dict[str, Any]:
    b = request.app.state.backend
    wu = await b.open_work_unit(
        id=body.id,
        project_id=body.project_id,
        title=body.title,
        description=body.description,
        system_ids=body.system_ids or None,
        created_by=actor_id,
    )
    return _serialize(wu)


@router.get("")
async def list_work_units(
    request: Request,
    project_id: str = Query(...),
    status: str | None = Query(None),
) -> list[dict[str, Any]]:
    b = request.app.state.backend
    results = await b.list_work_units(project_id, status=status)
    return [_serialize(wu) for wu in results]


@router.post("/{wu_id}/close")
async def close_work_unit(
    wu_id: str,
    request: Request,
    body: WorkUnitCloseBody | None = None,
    actor_id: str = Depends(require_actor_id),
) -> dict[str, Any]:
    del body  # placeholder for future status selection; currently always "done"
    b = request.app.state.backend
    result = await b.close_work_unit(wu_id, actor_id=actor_id)
    if not result:
        raise HTTPException(404, "Work unit not found or already closed")
    return _serialize(result)
