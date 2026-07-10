"""Upstream LLM provider adapter.

Wraps the outbound HTTP call to the configured chat-completions provider and
normalizes transport/rate-limit failures into a single UpstreamError the routes
can translate into a 502/503.
"""
from __future__ import annotations


class UpstreamError(Exception):
    """Raised when the upstream LLM provider is unavailable or returns an error."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status
