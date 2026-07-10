from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app import analytics
from app.auth import get_optional_user


router = APIRouter()

# Whole-batch backstop. Per-field truncation (analytics.sanitize_payload) and the client-side
# bound (telemetry.js) keep individual events well under this; the browser also splits batches
# below the limit, so this is a guard against a pathological caller, not the normal path.
MAX_TELEMETRY_BYTES = 256 * 1024


class TelemetryEvent(BaseModel):
    trace_id: str
    event_type: str
    timestamp: str
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_type")
    @classmethod
    def event_type_is_allowed(cls, value: str) -> str:
        if value not in analytics.ALLOWED_EVENT_TYPES:
            raise ValueError("unknown event_type")
        return value

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_iso8601(cls, value: str) -> str:
        # A malformed timestamp would reach sessions.started_at/ended_at and break the
        # ::timestamptz casts in metrics_snapshot. Reject at ingest. Client sends toISOString().
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("timestamp must be ISO-8601")
        return value


class TelemetryRequest(BaseModel):
    events: list[TelemetryEvent]


@router.post("/v1/telemetry", status_code=204)
def telemetry(request: TelemetryRequest, user: dict[str, Any] | None = Depends(get_optional_user)):
    # Sync route -> FastAPI runs the DB write in the threadpool, off the event loop. The whole
    # path is best-effort (analytics no-ops without a DB); identity is server-derived so a
    # caller can't attribute events to another user.
    size = len(request.model_dump_json().encode("utf-8"))
    if size > MAX_TELEMETRY_BYTES:
        raise HTTPException(status_code=413, detail={"error": "payload_too_large"})
    user_id = user["id"] if user else None
    analytics.record_telemetry([{**event.model_dump(), "user_id": user_id} for event in request.events])
    return None
