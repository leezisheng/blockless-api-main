"""Stateless LLM proxy for the browser-driven build loop.

POST /v1/llm/messages is the single endpoint the in-browser protocol loop calls
once per phase turn. The server is intentionally stateless: the browser owns the
phase state machine and the server holds the upstream key, requires auth, and
meters usage. Concrete provider wiring and prompt assembly are configured per
deployment.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user

router = APIRouter()
logger = logging.getLogger("blockless.llm")


class _ConcurrencyLimiter:
    """Non-blocking global + per-user caps on in-flight turns."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._global = 0
        self._per_user: dict[str, int] = {}

    def acquire(self, user_id: str, *, global_limit: int, user_limit: int) -> bool:
        with self._lock:
            if global_limit and self._global >= global_limit:
                return False
            if user_limit and self._per_user.get(user_id, 0) >= user_limit:
                return False
            self._global += 1
            self._per_user[user_id] = self._per_user.get(user_id, 0) + 1
            return True

    def release(self, user_id: str) -> None:
        with self._lock:
            self._global = max(0, self._global - 1)
            remaining = self._per_user.get(user_id, 0) - 1
            if remaining > 0:
                self._per_user[user_id] = remaining
            else:
                self._per_user.pop(user_id, None)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"global": self._global, "by_user": dict(self._per_user)}


_limiter = _ConcurrencyLimiter()


@router.post("/v1/llm/messages")
def messages(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    raise HTTPException(status_code=503, detail={"error": "llm_upstream_unconfigured"})
