from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.core.client_ip import client_ip


_WINDOW_SECONDS = 60
_MAX_REQUESTS = 60
_hits: dict[str, deque[float]] = defaultdict(deque)
_keyed_hits: dict[str, deque[float]] = defaultdict(deque)


def _sliding_window(bucket: deque[float], limit: int, window: int) -> None:
    now = time.monotonic()
    while bucket and now - bucket[0] > window:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(status_code=429, detail={"error": "rate_limited"})
    bucket.append(now)


def enforce(request: Request, *, limit: int = _MAX_REQUESTS) -> None:
    _sliding_window(_hits[client_ip(request)], limit, _WINDOW_SECONDS)


def enforce_key(key: str, *, limit: int, window: int = _WINDOW_SECONDS) -> None:
    """Per-arbitrary-key sliding window (e.g. f"publish:{user_id}" or f"like:{ip}"). Used to
    guard the authenticated social writes, which the per-IP landing limiter doesn't cover."""
    _sliding_window(_keyed_hits[key], limit, window)
