from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.skills import broker, catalog
from app.validation import providers


router = APIRouter()


class ValidateRequest(BaseModel):
    kind: str
    input: dict[str, Any] = Field(default_factory=dict)
    # The browser client enriches every validation call with the current project-store snapshot
    # (file_operation writes land here), so validators can read the artifact under test even when
    # the model passes an empty `input`. Each entry is {path, content}.
    files: list[dict[str, Any]] = Field(default_factory=list)


def default_capabilities() -> dict[str, Any]:
    return {
        "tools": catalog.allowed_primitives(),
        "webserial": True,
        "device_command": [
            "connect_request",
            "scan",
            "probe",
            "exec",
            "cp",
            "deploy",
            "cp_from",
            "ls",
            "mkdir",
            "rm",
            "statvfs",
            "soft_reset",
            "stream",
        ],
        "browser_validate": sorted(providers.IMPLEMENTED_KINDS),
        "artifact_store": ["read", "write", "list", "delete", "snapshot"],
        "firmware_flash_execute": False,
        "mpy_compile": False,
        "host_execution": False,
        "mpremote_backend": False,
    }


@router.get("/v1/build/capabilities")
def capabilities() -> dict[str, Any]:
    return default_capabilities()


@router.get("/v1/build/skills")
def skills() -> dict[str, Any]:
    return {
        "schema_version": catalog.manifest()["schema_version"],
        "allowed_primitives": catalog.allowed_primitives(),
        "skills": catalog.list_response(),
    }


@router.get("/v1/build/skills/{name}")
def skill_detail(name: str) -> dict[str, Any]:
    detail = catalog.detail_response(name)
    if detail is None:
        raise HTTPException(status_code=404, detail={"error": "skill_not_found"})
    return detail


# The validation/tool-call POSTs run during an authenticated build, so they require the
# session JWT -- they accept request bodies and do real work (ast.parse, contract checks),
# unlike the static GET discovery routes above which stay public for pre-auth listing.
@router.post("/v1/build/validate")
def validate(request: ValidateRequest, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    try:
        payload = dict(request.input)
        if request.files and "files" not in payload:
            payload["files"] = request.files
        return providers.validate(request.kind, payload)
    except broker.ContractViolation as error:
        raise HTTPException(status_code=400, detail={"error": "contract_violation", "message": str(error)})


@router.post("/v1/build/tool-calls/{skill_name}")
def validate_tool_call(skill_name: str, envelope: dict[str, Any], user: dict = Depends(get_current_user)) -> dict[str, Any]:
    try:
        return broker.validate_tool_call(skill_name, envelope, capabilities=default_capabilities())
    except broker.ContractViolation as error:
        raise HTTPException(status_code=400, detail={"error": "contract_violation", "message": str(error)})
