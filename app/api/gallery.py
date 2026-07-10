from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app import gallery_store, project_store
from app.auth import get_current_user
from app.core import rate_limit


router = APIRouter()


class PublishRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    icon: str | None = Field(default=None, max_length=16)
    tags: list[str] = Field(default_factory=list)
    parts: list[dict[str, Any]] = Field(default_factory=list)


class CommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


# --- public reads (no auth) -------------------------------------------------


@router.get("/v1/gallery")
def list_gallery(
    tag: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=60, ge=1, le=200),
) -> dict[str, Any]:
    return {"publications": gallery_store.list_publications(tag=tag, limit=limit)}


@router.get("/v1/gallery/{publication_id}")
def gallery_detail(publication_id: str) -> dict[str, Any]:
    try:
        return gallery_store.get_publication(publication_id)
    except gallery_store.PublicationNotFound:
        raise HTTPException(status_code=404, detail={"error": "publication_not_found"})


@router.get("/v1/gallery/{publication_id}/comments")
def gallery_comments(publication_id: str) -> dict[str, Any]:
    try:
        return {"comments": gallery_store.list_comments(publication_id)}
    except gallery_store.PublicationNotFound:
        raise HTTPException(status_code=404, detail={"error": "publication_not_found"})


# --- authenticated writes ---------------------------------------------------


@router.post("/v1/gallery/publish")
def publish(request: PublishRequest, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    rate_limit.enforce_key(f"publish:{user['id']}", limit=20)
    try:
        return gallery_store.publish(
            user,
            project_id=request.project_id,
            title=request.title,
            description=request.description,
            icon=request.icon,
            tags=request.tags,
            parts=request.parts,
        )
    except project_store.ProjectNotFound:
        raise HTTPException(status_code=404, detail={"error": "project_not_found"})


@router.post("/v1/gallery/{publication_id}/like")
def like(publication_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    rate_limit.enforce_key(f"like:{user['id']}", limit=120)
    try:
        return gallery_store.toggle_like(user, publication_id)
    except gallery_store.PublicationNotFound:
        raise HTTPException(status_code=404, detail={"error": "publication_not_found"})


@router.post("/v1/gallery/{publication_id}/comment")
def comment(publication_id: str, request: CommentRequest, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    rate_limit.enforce_key(f"comment:{user['id']}", limit=30)
    try:
        return gallery_store.add_comment(user, publication_id, request.body)
    except gallery_store.PublicationNotFound:
        raise HTTPException(status_code=404, detail={"error": "publication_not_found"})


@router.post("/v1/gallery/{publication_id}/remix")
def remix(publication_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    rate_limit.enforce_key(f"remix:{user['id']}", limit=30)
    try:
        return gallery_store.remix(user, publication_id)
    except gallery_store.PublicationNotFound:
        raise HTTPException(status_code=404, detail={"error": "publication_not_found"})
