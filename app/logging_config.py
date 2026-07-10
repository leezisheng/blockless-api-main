"""Structured (JSON) logging for blockless-web-api.

One JSON object per line on stdout so Render's log aggregation (and any drain) can
query by field. `setup_logging()` is idempotent and called once from the app
lifespan; `LOG_LEVEL` (default INFO) controls verbosity. Pass structured fields
via the stdlib `extra=` kwarg -- they are promoted to top-level JSON keys.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

# Attributes the stdlib puts on every LogRecord; anything else came from `extra=`.
_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # uvicorn installs its own handlers; route them through ours for one format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = [handler]
        lg.propagate = False
        lg.setLevel(level)
    _configured = True
    _init_sentry()


def _init_sentry() -> None:
    """Activate Sentry error tracking when SENTRY_DSN is set, else no-op. The dependency
    ships in requirements.txt; without a DSN local/test runs stay quiet. The stream and
    upstream failure paths are exactly what we want reported here."""
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return
    import sentry_sdk

    sentry_sdk.init(dsn=dsn, environment=os.getenv("MPYHW_ENV"))
