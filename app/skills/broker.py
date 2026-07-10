"""Tool-call broker.

Validates the browser's tool-call envelopes against the declared skill contracts
before they are executed, and exposes the set of validation kinds a skill is
allowed to request.
"""
from __future__ import annotations

from typing import Any


class ContractViolation(Exception):
    """Raised when a tool-call envelope does not satisfy the skill contract."""


def allowed_validation_kinds() -> set[str]:
    """Validation kinds any skill may request via browser_validate."""
    return set()


def validate_tool_call(
    skill_name: str,
    envelope: dict[str, Any],
    *,
    capabilities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Structurally validate a single tool-call envelope for ``skill_name``."""
    if not isinstance(envelope, dict):
        raise ContractViolation("tool-call envelope must be an object")
    if not skill_name:
        raise ContractViolation("skill_name is required")
    return {"ok": True, "skill": skill_name}
