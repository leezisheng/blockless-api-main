from __future__ import annotations

import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from starlette.concurrency import run_in_threadpool

from app import credit_store
from app.auth import get_current_user, mint_session, verify_google_token
from app.core import rate_limit


router = APIRouter()
logger = logging.getLogger(__name__)

# Process-local OAuth handshake state. The Render service runs WEB_CONCURRENCY=1, so a
# single worker owns both legs of the redirect dance and the one-time browser code.
_oauth_states: dict[str, dict[str, object]] = {}
_browser_codes: dict[str, dict[str, object]] = {}
_STATE_TTL_SECONDS = 10 * 60
_CODE_TTL_SECONDS = 5 * 60


def _now() -> float:
    return time.time()


def _cleanup() -> None:
    now = _now()
    for store in (_oauth_states, _browser_codes):
        for key, value in list(store.items()):
            if float(value.get("expires_at", 0)) < now:
                store.pop(key, None)


def _allowed_redirect_origins() -> set[str]:
    raw = os.getenv("MPYHW_BROWSER_AUTH_REDIRECT_ORIGINS", "https://block-less.com")
    return {item.strip().rstrip("/") for item in raw.split(",") if item.strip()}


def _origin_for(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail={"error": "invalid_redirect_uri"})
    return f"{parsed.scheme}://{parsed.netloc}"


def _callback_url() -> str:
    base = os.getenv("MPYHW_PUBLIC_API_BASE", "https://blockless-web-api.onrender.com").rstrip("/")
    return f"{base}/v1/auth/google/callback"


def _append_query(url: str, key: str, value: str) -> str:
    parsed = urllib.parse.urlparse(url)
    pairs = [(k, v) for (k, v) in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True) if k != key]
    pairs.append((key, value))
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(pairs)))


def exchange_google_code(code: str) -> str:
    """Trade the Google authorization code for an access token, server-side, using the
    client secret. The redirect_uri must match the one the auth request used."""
    client_id = os.getenv("MPYHW_GOOGLE_CLIENT_ID")
    client_secret = os.getenv("MPYHW_GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail={"error": "google_oauth_not_configured"})
    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": _callback_url(),
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=body,
        headers={"accept": "application/json", "content-type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail={"error": "google_oauth_unreachable"}) from exc
    access_token = data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=401, detail={"error": "google_oauth_failed"})
    return str(access_token)


@router.get("/v1/auth/google/start")
def google_start(redirect_uri: str = Query(...)) -> RedirectResponse:
    """Begin the Google OAuth dance: validate the front-end's return origin, then 302 the
    browser to Google with OUR backend callback as the redirect_uri (so the client secret
    never leaves the server)."""
    _cleanup()
    origin = _origin_for(redirect_uri)
    if origin not in _allowed_redirect_origins():
        raise HTTPException(status_code=400, detail={"error": "redirect_origin_not_allowed"})
    client_id = os.getenv("MPYHW_GOOGLE_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=500, detail={"error": "google_oauth_not_configured"})
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {"redirect_uri": redirect_uri, "expires_at": _now() + _STATE_TTL_SECONDS}
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": _callback_url(),
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
    )
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{query}")


@router.get("/v1/auth/google/callback")
async def google_callback(code: str = Query(...), state: str = Query(...)) -> RedirectResponse:
    """Google calls this back. Validate state, exchange the code for the user server-side,
    mint a SHORT one-time browser code, and redirect to the front-end's return URL with it."""
    _cleanup()
    state_payload = _oauth_states.pop(state, None)
    if not state_payload:
        # Unknown/expired state: there is no trusted frontend URI to bounce to, so surface a raw API
        # error (a test depends on this) rather than trusting an attacker-supplied redirect.
        raise HTTPException(status_code=400, detail={"error": "invalid_oauth_state"})
    redirect_uri = str(state_payload["redirect_uri"])
    try:
        access_token = await run_in_threadpool(exchange_google_code, code)
        user = await run_in_threadpool(verify_google_token, access_token)
    except Exception as exc:  # noqa: BLE001 - any exchange/verify failure must return the user to the app
        # We now hold a VALIDATED return URL, so bounce back to the frontend with an error param instead
        # of stranding the user on a raw JSON page at the API origin. Fail-loud: the error is surfaced on
        # the frontend where they can retry, AND logged here so an UNEXPECTED failure (a real bug, not a
        # known google_oauth_* HTTPException) isn't hidden by the redirect.
        detail = getattr(exc, "detail", None)
        error_code = detail.get("error") if isinstance(detail, dict) else None
        if error_code:
            code_str = str(error_code)
        else:
            code_str = "google_oauth_failed"
            logger.warning("unexpected google_callback failure: %r", exc)
        return RedirectResponse(_append_query(redirect_uri, "error", code_str))
    short_code = secrets.token_urlsafe(32)
    _browser_codes[short_code] = {"user": user, "expires_at": _now() + _CODE_TTL_SECONDS}
    return RedirectResponse(_append_query(redirect_uri, "code", short_code))


@router.post("/v1/auth/browser/exchange")
async def browser_exchange(request: Request) -> dict[str, Any]:
    """Swap the one-time browser code (minted by the callback) for a session JWT."""
    _cleanup()
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": "invalid_json"}) from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail={"error": "json_object_required"})
    code = str(body.get("code") or "")
    payload = _browser_codes.pop(code, None)
    if not payload:
        raise HTTPException(status_code=400, detail={"error": "invalid_auth_code"})
    user = payload["user"]
    return {"token": mint_session(user), "login": user.get("login")}


@router.post("/v1/auth/dev")
async def auth_dev(request: Request) -> dict[str, Any]:
    """Local-dev auth bypass, gated by MPYHW_ENABLE_DEV_AUTH=1. 404s in prod where the
    env flag is unset so it can never mint a session against the real OAuth backend."""
    if os.getenv("MPYHW_ENABLE_DEV_AUTH") != "1":
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    try:
        body = await request.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    login = str(body.get("login") or "local-dev")[:80]
    user = {"id": f"dev:{login}", "login": login, "email": None}
    return {"token": mint_session(user), "login": login}


# Set MPYHW_ALLOW_GUEST=0 to enforce login server-side (the web Builder now gates builds behind a
# Google sign-in; disabling guest closes the direct-API bypass). Default keeps the endpoint enabled
# so nothing that still relies on it breaks unexpectedly — flip it on Render to require login.
def _guest_allowed() -> bool:
    return os.getenv("MPYHW_ALLOW_GUEST", "1").strip().lower() not in ("0", "false", "no", "")


@router.post("/v1/auth/guest")
def auth_guest(request: Request) -> dict[str, Any]:
    """Mint an anonymous guest session so a visitor can build + simulate BEFORE signing in
    (the design's 'value before money'). A guest is a real JWT identity (`guest:<rand>`) with a
    small daily credit grant; the global free-tier daily budget + this per-IP rate limit are the
    abuse/cost ceilings. The browser stores the token so one visitor reuses one guest balance.
    Sign-in at 'Make it real' upgrades them to a full Google session."""
    if not _guest_allowed():
        raise HTTPException(status_code=403, detail={"error": "guest_disabled", "message": "Sign in to build."})
    rate_limit.enforce(request, limit=20)
    user = {"id": f"guest:{secrets.token_urlsafe(12)}", "login": None, "email": None}
    return {"token": mint_session(user), "login": None, "guest": True}


@router.get("/v1/credits")
def credits(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Current balance for display; ensures the daily grant on the first read of a day."""
    return credit_store.ensure_daily_grant(user, credit_store.grant_for(user))
