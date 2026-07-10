from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from app import auth, db
from app.api.auth import router as auth_router
from app.api.boards import router as boards_router
from app.api.admin import router as admin_router
from app.api.build import router as build_router
from app.api.enclosure import router as enclosure_router
from app.api import enclosure_skin
from app.api.gallery import router as gallery_router
from app.api.landing import router as landing_router
from app.api.llm import router as llm_router
from app.api.model_fetch import router as model_fetch_router
from app.api.projects import router as projects_router
from app.api.telemetry import router as telemetry_router
from app.core.config import BROWSER_SKILLS_ROOT, cors_origins
from app.health import router as health_router
from app.logging_config import setup_logging


logger = logging.getLogger("blockless.request")
startup_log = logging.getLogger("blockless.startup")

_BODY_LIMITS = {
    "/v1/landing/newsletter": 1024,
    "/v1/landing/recommend": 4096,
    "/v1/build/validate": 512 * 1024,
    "/v1/auth/browser/exchange": 8192,
    # Per-phase generate turn carries the manifest + growing message/tool-result history. A long
    # phase (many select-hw/generate turns, each re-sent in full by the stateless protocol) can
    # push this past 1 MB; the cap is a DoS guard, not a context bound (DeepSeek's own context
    # window is the real ceiling), so allow headroom before a turn is rejected.
    "/v1/llm/messages": 2 * 1024 * 1024,
    # Telemetry batches; the browser splits below this and the route 413s a pathological one.
    "/v1/telemetry": 256 * 1024,
    # Saved builds + gallery publishes carry the artifact snapshot (code + board + wiring +
    # conversation). These body limits are exact-path lookups (see RequestBodyLimitMiddleware),
    # so the snapshot-carrying social writes deliberately live at fixed paths (never /{id}).
    "/v1/projects/create": 1024 * 1024,
    "/v1/projects/update": 1024 * 1024,
    "/v1/gallery/publish": 1024 * 1024,
}


def validate_config() -> None:
    if not (BROWSER_SKILLS_ROOT / "browser_skill_manifest.json").is_file():
        raise RuntimeError("browser-micropython-skills manifest is missing")

    if os.getenv("MPYHW_ENV") != "prod":
        return

    db._database_url()
    try:
        auth._jwt_secret()
    except HTTPException as exc:
        raise RuntimeError("MPYHW_JWT_SECRET is not configured") from exc
    missing = [
        name
        for name in (
            "DEEPSEEK_API_KEY",
            "MPYHW_GOOGLE_CLIENT_ID",
            "MPYHW_GOOGLE_CLIENT_SECRET",
        )
        if not os.getenv(name)
    ]
    if missing:
        raise RuntimeError(f"missing required prod secrets: {', '.join(missing)}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    validate_config()
    try:
        if os.getenv("DATABASE_URL"):
            db.initialize()
            db.open_pool()
    except Exception:
        startup_log.warning("startup db init/pool open failed; readiness probe gates traffic", exc_info=True)
    try:
        yield
    finally:
        db.close_pool()


class RequestLogMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.monotonic()
        status = {"code": 0}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope.get("path", "")
            if path not in ("/v1/health", "/v1/health/ready"):
                # The browser sends X-Trace-Id (the per-build id) on every call, so one log
                # search by trace_id returns the whole request chain (LLM turns + validate +
                # telemetry). Read it from the header, not the body (we don't parse the body here).
                trace_id = dict(scope.get("headers", [])).get(b"x-trace-id", b"").decode("ascii", "ignore") or None
                logger.info(
                    "request",
                    extra={
                        "method": scope.get("method"),
                        "path": path,
                        "status": status["code"],
                        "duration_ms": int((time.monotonic() - start) * 1000),
                        "trace_id": trace_id,
                    },
                )


class RequestBodyLimitMiddleware:
    def __init__(self, app, limits: dict[str, int]):
        self.app = app
        self.limits = limits

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        limit = self.limits.get(scope.get("path", ""))
        if not limit:
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                if int(raw_length.decode("ascii")) > limit:
                    await self._reject(scope, send, limit)
                    return
            except ValueError:
                await self._reject(scope, send, limit)
                return

        messages = []
        total = 0
        more_body = True
        while more_body:
            message = await receive()
            messages.append(message)
            if message.get("type") == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    await self._reject(scope, send, limit)
                    return
                more_body = bool(message.get("more_body", False))
            else:
                more_body = False

        index = 0

        async def replay_receive():
            nonlocal index
            if index < len(messages):
                message = messages[index]
                index += 1
                return message
            # Buffered body is exhausted -> delegate to the real receive so callers BLOCK on the
            # underlying transport (e.g. StreamingResponse's listen_for_disconnect waiting for
            # http.disconnect). Returning a synthetic http.request here instead spins that
            # `while True: await receive()` watcher at 100% CPU, freezing the worker for the whole
            # stream -- which is exactly what hung every streaming /v1/llm/messages build.
            return await receive()

        await self.app(scope, replay_receive, send)

    async def _reject(self, scope: dict[str, Any], send, limit: int) -> None:
        response = JSONResponse({"detail": {"error": "request_body_too_large", "max_bytes": limit}}, status_code=413)
        await response(scope, None, send)


app = FastAPI(title="blockless-api", version="1.0.0", lifespan=lifespan)
# Middleware runs outermost-last: add_middleware() prepends, so the LAST add wraps everything.
# The body-limit + request-log middleware go on first (inner); CORS goes on LAST (outermost) so
# that a pre-route rejection -- notably RequestBodyLimitMiddleware's 413 -- still flows OUT through
# CORS and keeps its Access-Control-Allow-Origin header. If CORS were inner, that 413 would reach
# the browser header-less; the browser then blocks it and fetch() throws a bare "Failed to fetch"
# the app can neither read nor surface (a silent-failure regression -- the build just dies).
app.add_middleware(RequestBodyLimitMiddleware, limits=_BODY_LIMITS)
app.add_middleware(RequestLogMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["GET", "POST", "OPTIONS"],
    # x-trace-id: per-build correlation id the browser sends on every call (must pass preflight).
    # x-admin-token: gate for the /v1/admin/* read endpoints.
    allow_headers=["authorization", "content-type", "x-trace-id", "x-admin-token"],
)
app.include_router(health_router)
app.include_router(landing_router)
app.include_router(auth_router)
app.include_router(build_router)
app.include_router(enclosure_router)
app.include_router(enclosure_skin.router)
app.include_router(boards_router)
app.include_router(llm_router)
app.include_router(telemetry_router)
app.include_router(admin_router)
app.include_router(model_fetch_router)
app.include_router(projects_router)
app.include_router(gallery_router)
