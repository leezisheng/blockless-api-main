"""Google identity + session JWT.

`get_current_user` is a FastAPI dependency that protected routes depend on; it
reads the `Authorization: Bearer <jwt>` header and returns the user. The JWT is
minted after verifying a Google access token through the web OAuth flow.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any

from fastapi import Header, HTTPException

from app import session_token

JWT_TTL_SECONDS = int(os.getenv("MPYHW_JWT_TTL", str(24 * 3600)))
DEFAULT_JWT_SECRET = "dev-insecure-secret"
logger = logging.getLogger("mpyhw.auth")


def _jwt_secret() -> str:
    # Fail closed in EVERY environment because the default is public source-code
    # value and would let anyone forge user JWTs if a deploy forgot the secret.
    secret = os.getenv("MPYHW_JWT_SECRET", DEFAULT_JWT_SECRET)
    if not secret or secret == DEFAULT_JWT_SECRET:
        raise HTTPException(status_code=500, detail={"error": "jwt_secret_not_configured"})
    return secret


def mint_session(user: dict[str, Any]) -> str:
    payload = {"sub": user["id"], "login": user.get("login"), "email": user.get("email")}
    return session_token.encode(payload, _jwt_secret(), JWT_TTL_SECONDS)


def get_current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail={"error": "auth_required"})
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = session_token.decode(token, _jwt_secret())
    except session_token.TokenError:
        raise HTTPException(status_code=401, detail={"error": "invalid_token"})
    return {"id": payload["sub"], "login": payload.get("login"), "email": payload.get("email")}


def get_optional_user(authorization: str | None = Header(default=None)) -> dict[str, Any] | None:
    """Like `get_current_user` but never raises: returns the user on a valid bearer token,
    else None. Telemetry ingest must stay fail-soft, so this swallows EVERYTHING -- a missing
    header, a bad token, AND the HTTPException(500) `_jwt_secret()` raises when the secret is
    unset/misconfigured (a config error must not turn anonymous telemetry into a 500)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = session_token.decode(token, _jwt_secret())
    except Exception:
        return None
    return {"id": payload["sub"], "login": payload.get("login"), "email": payload.get("email")}


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """Gate the /v1/admin/* read endpoints. Fail-closed: if MPYHW_ADMIN_TOKEN is unset the
    admin surface is simply off (401), so a deploy that forgot the secret can't expose
    metrics/replay. Constant-time compare avoids leaking the token by timing."""
    expected = os.getenv("MPYHW_ADMIN_TOKEN")
    if not expected:
        raise HTTPException(status_code=401, detail={"error": "admin_disabled"})
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail={"error": "admin_unauthorized"})


def verify_google_token(access_token: str) -> dict[str, Any]:
    """Exchange a Google access token for the stable user id/login/email."""
    request = urllib.request.Request(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={
            "authorization": f"Bearer {access_token}",
            "user-agent": "blockless-web-api",
            "accept": "application/json",
        },
    )
    backoffs = (0.25, 0.5)  # 3 attempts total
    for attempt in range(len(backoffs) + 1):
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
            sub = data.get("sub")
            if not sub:
                raise HTTPException(status_code=401, detail={"error": "google_auth_failed"})
            email = data.get("email")
            login = email or data.get("name") or str(sub)
            return {"id": f"google:{sub}", "login": login, "email": email}
        except urllib.error.HTTPError as error:
            if error.code >= 500 and attempt < len(backoffs):
                logger.warning("google verify retry", extra={"status": error.code, "attempt": attempt + 1})
                time.sleep(backoffs[attempt])
                continue
            raise HTTPException(status_code=401, detail={"error": "google_auth_failed", "status": error.code})
        except urllib.error.URLError:
            if attempt < len(backoffs):
                logger.warning("google verify retry", extra={"status": 0, "attempt": attempt + 1})
                time.sleep(backoffs[attempt])
                continue
            raise HTTPException(status_code=502, detail={"error": "google_unreachable"})
