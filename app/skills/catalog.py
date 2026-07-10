"""Browser-skill catalog.

A thin, typed read-view over the browser-micropython-skills manifests used by the
/v1/build/skills discovery routes. The concrete skill definitions live in the
``third_party/browser-micropython-skills`` submodule.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

_SCHEMA_VERSION = "1.0.0"

# Protocol primitives the browser build loop is permitted to emit.
_ALLOWED_PRIMITIVES = [
    "approval_request",
    "file_operation",
    "device_command",
    "browser_validate",
    "phase_complete",
]


def allowed_primitives() -> list[str]:
    return list(_ALLOWED_PRIMITIVES)


@lru_cache(maxsize=1)
def manifest() -> dict[str, Any]:
    return {"schema_version": _SCHEMA_VERSION, "skills": []}


def list_response() -> list[dict[str, Any]]:
    """Summary rows for the skill picker."""
    return []


def detail_response(name: str) -> dict[str, Any] | None:
    """Full skill detail, or None when the name is unknown."""
    return None
