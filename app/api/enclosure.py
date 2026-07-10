"""Enclosure export route: regenerate the deterministic case geometry on demand.

Deliberately NOT part of /v1/models (that route is a license-gated catalog of
pre-cleared third-party assets); a generated enclosure is a per-build artifact
that the generator can recompute byte-for-byte from its descriptor inputs, so
nothing is stored — export = plan + build + stream.

Requires the CAD kernel (cadquery, a dev/enclosure-time dependency): when it is
absent this route fails loudly with enclosure_export_unavailable instead of
degrading. The whole route sits behind the frontend ENCLOSURE_ENABLED flag in
v1 (flag off in prod).
"""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.enclosure import generator, profiles

router = APIRouter()

_MEDIA_TYPES = {"step": "application/step", "stl": "model/stl"}
# OCCT geometry builds are CPU-heavy; cap concurrent exports so an authenticated caller
# cannot saturate the worker (WEB_CONCURRENCY=1 in prod). Saturated -> loud 429, no queueing.
_EXPORT_SLOTS = threading.BoundedSemaphore(2)


class EnclosureExportRequest(BaseModel):
    board_slug: str = Field(min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)
    modules: list[str] = Field(default_factory=list)
    part: Literal["tray", "lid"] = "tray"
    fmt: Literal["step", "stl"] = "stl"


@router.post("/v1/enclosure/export")
def export_enclosure(request: EnclosureExportRequest, user: dict = Depends(get_current_user)) -> Response:
    try:
        descriptor = generator.plan_enclosure(request.board_slug, request.params, request.modules)
    except profiles.ProfileNotFound as error:
        raise HTTPException(status_code=404, detail={"error": "enclosure_profile_missing", "message": str(error)})
    except profiles.ProfileInvalid as error:
        raise HTTPException(status_code=500, detail={"error": "enclosure_profile_invalid", "message": str(error)})
    except generator.ParamsInvalid as error:
        raise HTTPException(status_code=400, detail={"error": "enclosure_params_invalid", "message": str(error)})
    if not descriptor["drc"]["pass"]:
        raise HTTPException(
            status_code=422,
            detail={"error": "enclosure_drc_failed", "violations": descriptor["drc"]["violations"]},
        )
    if request.part == "lid" and descriptor["params"]["lid"] == "none":
        raise HTTPException(status_code=400, detail={"error": "enclosure_no_lid", "message": "this configuration has no lid"})

    if not _EXPORT_SLOTS.acquire(blocking=False):
        raise HTTPException(status_code=429, detail={"error": "enclosure_export_busy", "message": "too many concurrent enclosure exports; retry shortly"})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                files = generator.export_files(descriptor, tmp, parts=[request.part], formats=[request.fmt])
            except RuntimeError as error:  # cadquery missing or OCCT build/validity failure
                raise HTTPException(status_code=503, detail={"error": "enclosure_export_unavailable", "message": str(error)})
            key = f"{request.part}.{request.fmt}"
            data = Path(files[key]).read_bytes()
    finally:
        _EXPORT_SLOTS.release()

    filename = f"enclosure_{request.board_slug}_{request.part}.{request.fmt}"
    return Response(
        content=data,
        media_type=_MEDIA_TYPES[request.fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
