"""Board picker schemas."""
from __future__ import annotations

from pydantic import BaseModel


class BoardSummary(BaseModel):
    board_id: str
    display_name: str
    chip_family: str | None = None
    pin_allocation_supported: bool = False


class BoardCatalogResponse(BaseModel):
    version: str
    board_count: int
    pin_supported_count: int
    boards: list[BoardSummary]
