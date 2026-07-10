from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field, field_validator

from app import recommendation_catalog, web_recommend, web_store
from app.core import rate_limit


router = APIRouter()
logger = logging.getLogger(__name__)


def _recommended_board_dict(board: dict, slug: str | None, links: list, primary: dict | None) -> dict:
    firmware = board.get("firmware") or {}
    release = firmware.get("latest_release") or {}
    return {
        "name": board.get("name") or slug or "MicroPython board",
        "why": "Beginner-friendly MicroPython target with official firmware and purchase guidance.",
        "buy_url": primary["url"] if primary else None,
        "primary_link": primary,
        "purchase_links": links,
        "micropython_url": board.get("detail_url"),
        "firmware_url": release.get("url"),
        "source": "micropython_catalog",
        "model": recommendation_catalog.board_model(slug),
    }


class NewsletterRequest(BaseModel):
    email: EmailStr = Field(max_length=254)
    locale: str = Field(default="en", max_length=8)
    source: str = Field(default="landing", max_length=64)


class RecommendRequest(BaseModel):
    idea: str = Field(min_length=1, max_length=500)
    locale: str = Field(default="en", max_length=8)
    region: str = Field(default="us", max_length=32)

    @field_validator("idea")
    @classmethod
    def _idea_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("idea must not be blank")
        return value


@router.post("/v1/landing/newsletter", status_code=204)
def newsletter(request: NewsletterRequest, http_request: Request) -> Response:
    rate_limit.enforce(http_request)
    web_store.record_newsletter_signup(str(request.email), request.locale, request.source)
    return Response(status_code=204)


@router.post("/v1/landing/recommend")
def recommend(request: RecommendRequest, http_request: Request) -> dict[str, Any]:
    # Anonymous endpoint: spend is bounded by a per-IP rate limit plus the global daily
    # LLM-call cap inside web_recommend. Fail fast -- an unusable LLM returns an explicit
    # 503/422 from web_recommend.recommend, never a masked keyword guess or stub board.
    web_recommend.enforce_rate_limit(http_request)
    idea = request.idea.strip()
    result = web_recommend.recommend(idea, region=request.region)
    # The pipeline already chose the board (idea-driven: a board-family hint picks a
    # board of that family), so don't re-select it here.
    board = result.get("board")
    purchase_links = recommendation_catalog.load_purchase_links(request.region)
    starter_prompt = f"Build a MicroPython project for: {idea}"
    handoff = {
        "starter_prompt": starter_prompt,
        "locale": request.locale,
        "region": request.region,
        "board_slug": board.get("slug") if board else None,
        "capabilities": result["capabilities"],
        "board_family_hint": result["board_family_hint"],
    }
    if board:
        slug = board.get("slug")
        # Curated, verified, buyable product page first; then the generated catalog links.
        # Family/SoC pages are stripped so they can neither be the buy action nor leak in
        # purchase_links. The front-end shows only the single primary_link.
        curated = recommendation_catalog.board_purchase_links(slug, request.region)
        seen_urls = {link.get("url") for link in curated}
        generated = purchase_links.get(slug, []) if slug else []
        links = recommendation_catalog.filter_buyable_links(
            curated + [link for link in generated if link.get("url") not in seen_urls]
        )
        primary = recommendation_catalog.select_primary_link(links)
        if primary is None:
            # Sim-first version: purchasability is not a precondition -- the simulator is the
            # deliverable. Keep the board; surface the data gap in logs only.
            logger.warning("web recommend: no buyable purchase link for board %s (non-blocking)", slug)
        recommended_board = _recommended_board_dict(board, slug, links, primary)
    else:
        # Fail fast: no board means the board catalog is empty/broken (a deploy-time data
        # gap), not a normal outcome. Surface it loudly rather than serving a hardcoded guess.
        logger.error("web recommend: recommendation returned no board (empty board catalog?)")
        raise HTTPException(status_code=500, detail={"error": "board_catalog_empty"})
    recipe = {
        "recommended_board": recommended_board,
        "parts": result["parts"],
        "starter_prompt": starter_prompt,
        "handoff": handoff,
        "source": result["source"],
        # Short LLM-generated project name (idea-derived, board/part-free). The Builder shows
        # this as the top-bar title instead of the recommended board; None for a vague idea the
        # model didn't name (the UI then falls back to "New build"). Survives recipe reload.
        "title": result.get("name"),
    }
    recipe_id = web_store.record_web_recipe(recipe)
    return {**recipe, "recipe_id": recipe_id}


@router.get("/v1/landing/recipes/{recipe_id}")
def recipe(recipe_id: str) -> dict[str, Any]:
    loaded = web_store.load_web_recipe(recipe_id)
    if loaded is None:
        raise HTTPException(status_code=404, detail={"error": "recipe_not_found"})
    return loaded

