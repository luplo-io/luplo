"""Project routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from luplo.server.auth.deps import CurrentActor, get_current_actor

router = APIRouter()


class ProjectCreate(BaseModel):
    id: str
    name: str
    description: str | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str | None
    created_at: str


def _serialize(p: Any) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "created_at": p.created_at.isoformat(),
    }


@router.post("", status_code=201)
async def create_project(
    body: ProjectCreate,
    request: Request,
    actor: CurrentActor = Depends(get_current_actor),
) -> dict[str, Any]:
    b = request.app.state.backend
    p = await b.create_project(id=body.id, name=body.name, description=body.description)
    return _serialize(p)


@router.get("/{project_id}")
async def get_project(project_id: str, request: Request) -> dict[str, Any]:
    b = request.app.state.backend
    p = await b.get_project(project_id)
    if not p:
        from fastapi import HTTPException

        raise HTTPException(404, "Project not found")
    return _serialize(p)


@router.get("")
async def list_projects(request: Request) -> list[dict[str, Any]]:
    b = request.app.state.backend
    return [_serialize(p) for p in await b.list_projects()]
