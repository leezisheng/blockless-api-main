import os
import re
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.easyeda_client import EasyEdaError, fetch_model_asset
from app.recommendation_catalog import model_asset_index, model_catalog

router = APIRouter()

# Servable key: alphanumerics + _ - only. Validated BEFORE any lookup/path use so a key can
# never carry a path separator, '.', or traversal into fetch_model_asset.
_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")


def _enabled() -> bool:
    # ON by default: per-entry licensing is enforced by the cleared+provenance gates below,
    # so the env var is only an emergency kill switch (set MPYHW_ENABLE_MODEL_FETCH=0).
    return os.getenv("MPYHW_ENABLE_MODEL_FETCH", "1") == "1"


def _valid_provenance(entry: dict) -> bool:
    """Cleared-and-servable requires verified provenance: an attribution string and a real
    http(s) source_url. The CI integrity test enforces this on the committed registry; this
    is the runtime fail-closed backstop so a bad row can never be served."""
    u = urlparse(str(entry.get("source_url") or ""))
    return bool(str(entry.get("attribution") or "").strip()) and u.scheme in {"http", "https"} and bool(u.netloc)


@router.get("/v1/models")
def models_index() -> dict:
    """Public index of servable (license-cleared) 3D models for the Stage.
    `enabled: false` = feature env-gated off (frontend renders "coming soon");
    an enabled-but-thin list is a real coverage gap the frontend surfaces loudly."""
    if not _enabled():
        return {"enabled": False, "models": []}
    models = []
    for row in model_catalog():
        if row["license_status"] != "cleared":
            continue
        if not _valid_provenance(row):
            # Fail-closed: a cleared entry without verified provenance is OUR bug — never serve it.
            raise HTTPException(status_code=500, detail={"error": "model_provenance_missing", "key": row["key"]})
        models.append({k: v for k, v in row.items() if k not in {"license_status", "source_url"}})
    return {"enabled": True, "models": models}


@router.get("/v1/models/{key}")
def model(key: str) -> Response:
    """Serve a committed, license-cleared 3D model asset (GLB or OBJ) by key. Bundled-only;
    the route serves exactly the registry-declared file. Gated off until license sign-off."""
    if not _enabled():
        raise HTTPException(status_code=404, detail={"error": "model_fetch_disabled"})
    if not _KEY_RE.match(key):
        raise HTTPException(status_code=400, detail={"error": "bad_key"})
    entry = model_asset_index().get(key)
    if entry is None:
        raise HTTPException(status_code=404, detail={"error": "unknown_model"})
    if entry["license_status"] != "cleared":
        # License gate: an un-cleared asset must never be served publicly.
        raise HTTPException(status_code=404, detail={"error": "model_not_cleared"})
    if not _valid_provenance(entry):
        raise HTTPException(status_code=500, detail={"error": "model_provenance_missing", "key": key})
    try:
        data, content_type = fetch_model_asset(entry["file"])
    except EasyEdaError as exc:
        code = str(exc)
        if code == "asset_missing":
            raise HTTPException(status_code=404, detail={"error": code})
        # corrupt / unreadable / bad committed asset -> our bug, not the client's
        raise HTTPException(status_code=502, detail={"error": "asset_error", "reason": code})
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )
