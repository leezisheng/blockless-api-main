from __future__ import annotations

from fastapi import HTTPException


def bad_request(error: str, **extra: object) -> HTTPException:
    return HTTPException(status_code=400, detail={"error": error, **extra})


def not_found(error: str, **extra: object) -> HTTPException:
    return HTTPException(status_code=404, detail={"error": error, **extra})


def capability_required(capability: str, **extra: object) -> dict[str, object]:
    return {"status": "partial", "capability_required": capability, **extra}

