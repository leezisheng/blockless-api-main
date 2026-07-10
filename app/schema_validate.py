"""Driver-context schema validation."""
from __future__ import annotations

from typing import Any


class SchemaError(Exception):
    """Raised when a driver context does not conform to the schema."""


def validate_driver_context(context: dict[str, Any]) -> None:
    """Validate ``context`` against the driver-context schema (no-op on success)."""
    if not isinstance(context, dict):
        raise SchemaError("driver context must be an object")
