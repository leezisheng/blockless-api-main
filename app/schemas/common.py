"""Shared response envelopes used across the API routes."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorEnvelope(BaseModel):
    """Standard error body: ``{"detail": {"error": ..., "message": ...}}``."""

    error: str
    message: str | None = None


class ValidationResult(BaseModel):
    """Result envelope returned by browser_validate gates."""

    kind: str
    ok: bool
    checks: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class Pagination(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
