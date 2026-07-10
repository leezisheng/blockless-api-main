from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import project_store
from app.auth import get_current_user
from app.core import rate_limit


router = APIRouter()

# Per-user write ceiling (auto-save fires fairly often during a build, so keep it generous).
_WRITE_LIMIT = 120


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    icon: str | None = Field(default=None, max_length=16)
    board_id: str | None = Field(default=None, max_length=64)
    status: str = Field(default="draft", max_length=32)
    snapshot: dict[str, Any] = Field(default_factory=dict)
    conversation: Any = None
    remixed_from: str | None = Field(default=None, max_length=64)


class ProjectUpdate(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    title: str | None = Field(default=None, max_length=200)
    icon: str | None = Field(default=None, max_length=16)
    board_id: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=32)
    snapshot: dict[str, Any] | None = None
    conversation: Any = None


class ProjectRef(BaseModel):
    id: str = Field(min_length=1, max_length=64)


@router.post("/v1/projects/create")
def create(request: ProjectCreate, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    rate_limit.enforce_key(f"project_write:{user['id']}", limit=_WRITE_LIMIT)
    try:
        return project_store.create_project(
            user,
            title=request.title,
            icon=request.icon,
            board_id=request.board_id,
            status=request.status,
            snapshot=request.snapshot,
            conversation=request.conversation,
            remixed_from=request.remixed_from,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"error": "invalid_project", "message": str(error)})


@router.post("/v1/projects/update")
def update(request: ProjectUpdate, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    rate_limit.enforce_key(f"project_write:{user['id']}", limit=_WRITE_LIMIT)
    try:
        return project_store.update_project(
            user,
            request.id,
            title=request.title,
            icon=request.icon,
            board_id=request.board_id,
            status=request.status,
            snapshot=request.snapshot,
            conversation=request.conversation,
        )
    except project_store.ProjectNotFound:
        raise HTTPException(status_code=404, detail={"error": "project_not_found"})
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"error": "invalid_project", "message": str(error)})


@router.post("/v1/projects/delete")
def delete(request: ProjectRef, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    rate_limit.enforce_key(f"project_write:{user['id']}", limit=_WRITE_LIMIT)
    try:
        project_store.delete_project(user, request.id)
    except project_store.ProjectNotFound:
        raise HTTPException(status_code=404, detail={"error": "project_not_found"})
    return {"ok": True}


@router.get("/v1/projects")
def list_projects(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    return {"projects": project_store.list_projects(user)}


@router.get("/v1/projects/{project_id}")
def get_project(project_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    try:
        return project_store.get_project(user, project_id)
    except project_store.ProjectNotFound:
        raise HTTPException(status_code=404, detail={"error": "project_not_found"})
