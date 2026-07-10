"""POST /v1/enclosure/skin/generate + artifact serving (v2b skin pipeline).

REAL backend kill-switch MPYHW_ENABLE_SKIN_GEN (default OFF). Accepted,
documented limitation: generation holds a worker for minutes (WEB_CONCURRENCY=1
-> one build at a time); fine while flag-gated, job queue is future work.
Artifacts persist ONLY when gates pass; key = manifest_sha256."""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app.auth import get_current_user
from app.enclosure import generator, profiles, skin_backend, skin_mesh
from app.enclosure.generator import ParamsInvalid

router = APIRouter(prefix="/v1/enclosure/skin", tags=["enclosure"])

_SLOTS = threading.BoundedSemaphore(1)
_KEY_RE = re.compile(r"^[0-9a-f]{64}$")


def _enabled() -> bool:
    return os.getenv("MPYHW_ENABLE_SKIN_GEN", "0") == "1"


def _artifact_dir() -> Path:
    p = Path(os.getenv("MPYHW_SKIN_ARTIFACT_DIR", "var/skin_artifacts"))
    p.mkdir(parents=True, exist_ok=True)
    return p


class SkinGenerateRequest(BaseModel):
    prompt: str
    board_slug: str
    params: dict = {}
    modules: list[str] = []
    bed_w: float = 220.0
    bed_h: float = 220.0


@router.post("/generate")
def generate(req: SkinGenerateRequest, user=Depends(get_current_user)):
    if not _enabled():
        raise HTTPException(403, {"error": "skin_generation_disabled"})
    if not _SLOTS.acquire(blocking=False):
        raise HTTPException(429, {"error": "skin_generate_busy"})
    try:
        try:
            descriptor = generator.plan_enclosure(req.board_slug, req.params, req.modules)
        except profiles.ProfileNotFound:
            raise HTTPException(404, {"error": "profile_missing"})
        except profiles.ProfileInvalid:
            raise HTTPException(500, {"error": "profile_invalid"})
        except ParamsInvalid as exc:
            raise HTTPException(400, {"error": "params_invalid", "detail": str(exc)})
        if not descriptor["drc"]["pass"]:
            raise HTTPException(422, {"error": "enclosure_drc_failed",
                                      "violations": descriptor["drc"]["violations"]})
        try:
            gen = skin_backend.generate_skin(req.prompt)
            build = skin_mesh.build_skin(gen, descriptor, bed=(req.bed_w, req.bed_h))
        except skin_backend.SkinBackendError as exc:
            raise HTTPException(502, {"error": "skin_generation_failed",
                                      "detail": str(exc)})
        except skin_mesh.SkinMeshError as exc:
            raise HTTPException(422, {"error": "skin_geometry_failed",
                                      "detail": str(exc)})
        except skin_mesh.SkinUnavailable:
            raise HTTPException(503, {"error": "skin_unavailable"})
        payload = {"manifest": build.manifest, "gate_report": build.gate_report}
        if not build.gate_report["pass"]:
            raise HTTPException(422, {"error": "skin_gate_failed", **payload})
        key = skin_mesh.manifest_key(build.manifest)
        d = _artifact_dir()
        (d / f"{key}.glb").write_bytes(build.preview_glb)
        (d / f"{key}.pos_y.stl").write_bytes(build.halves[0])
        (d / f"{key}.neg_y.stl").write_bytes(build.halves[1])
        (d / f"{key}.manifest.json").write_text(
            json.dumps(build.manifest, sort_keys=True), encoding="utf-8")
        return {**payload, "preview_key": key}
    finally:
        _SLOTS.release()


def _load(key: str, suffix: str) -> bytes:
    if not _KEY_RE.fullmatch(key):
        raise HTTPException(404, {"error": "skin_artifact_not_found"})
    p = _artifact_dir() / f"{key}{suffix}"
    if not p.is_file():
        raise HTTPException(404, {"error": "skin_artifact_not_found"})
    return p.read_bytes()


@router.get("/{key}.glb")
def preview(key: str, user=Depends(get_current_user)):
    return Response(_load(key, ".glb"), media_type="model/gltf-binary",
                    headers={"Cache-Control": "private, max-age=86400"})


@router.get("/{key}/half/{side}.stl")
def half(key: str, side: str, user=Depends(get_current_user)):
    if side not in ("pos_y", "neg_y"):
        raise HTTPException(404, {"error": "skin_artifact_not_found"})
    return Response(_load(key, f".{side}.stl"), media_type="model/stl",
                    headers={"Content-Disposition":
                             f'attachment; filename="skin_{side}.stl"'})
