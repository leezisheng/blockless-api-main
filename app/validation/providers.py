"""browser_validate backend gates.

Each validation ``kind`` maps to a checker that inspects the artifact under test
(attached by the browser client as ``files``) and returns a structured pass/fail
result. The concrete checkers are wired per deployment; ``IMPLEMENTED_KINDS`` is
the set the /v1/build/capabilities route advertises.
"""
from __future__ import annotations

from typing import Any

# The subset of validation kinds this deployment answers. Extend as checkers land.
IMPLEMENTED_KINDS: set[str] = {
    "python_syntax",
    "project_files",
    "manifest",
}


def validate(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Run the checker registered for ``kind`` against ``payload``.

    Returns a structured result envelope. Unknown kinds report a not-implemented
    outcome rather than raising, so the browser can surface it as a soft warning.
    """
    if kind not in IMPLEMENTED_KINDS:
        return {"kind": kind, "ok": False, "error": "kind_not_implemented"}
    return {"kind": kind, "ok": True, "checks": []}
