from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app import analytics
from app.auth import require_admin


router = APIRouter()


@router.get("/v1/admin/metrics")
def metrics(_: None = Depends(require_admin)) -> dict[str, Any]:
    return analytics.metrics_snapshot()


@router.get("/v1/admin/sessions/{trace_id}")
def session_detail(trace_id: str, _: None = Depends(require_admin)) -> dict[str, Any]:
    """Pull a whole build by trace_id -- the session summary row, the ordered raw event
    trace, and its LLM turns -- so a failed/hung build is one authenticated curl instead of
    a direct DB query."""
    return {
        "session": analytics.session_for(trace_id=trace_id),
        "events": analytics.telemetry_events(trace_id=trace_id),
        "llm_turns": analytics.llm_turns_for(trace_id=trace_id),
    }
