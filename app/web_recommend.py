"""Website hardware recommendation.

Turns a natural-language idea into a grounded list of real catalog modules:
extract capabilities, query the curated package catalog per capability, and
assemble a deduped parts list with a recommended board. Spend on the anonymous
endpoint is bounded by a per-IP rate limit and a global daily call cap.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

from app.core.client_ip import client_ip

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 60.0
_MAX_PER_WINDOW = 6

_rate_lock = threading.Lock()
_rate_hits: dict[str, deque[float]] = {}


def reset() -> None:
    """Clear in-process rate-limit state (tests)."""
    with _rate_lock:
        _rate_hits.clear()


def enforce_rate_limit(request: Request) -> None:
    """Per-IP sliding-window limit for the anonymous recommend endpoint."""
    ip = client_ip(request)
    now = time.monotonic()
    with _rate_lock:
        hits = _rate_hits.setdefault(ip, deque())
        while hits and now - hits[0] > _WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= _MAX_PER_WINDOW:
            raise HTTPException(status_code=429, detail={"error": "rate_limited"})
        hits.append(now)


def recommend(idea: str, *, region: str = "us") -> dict:
    """Recommend a board + parts for ``idea``.

    The public build does not ship the capability-extraction pipeline, so this
    fails loudly rather than returning a masked guess.
    """
    raise HTTPException(status_code=503, detail={"error": "recommend_unconfigured"})
