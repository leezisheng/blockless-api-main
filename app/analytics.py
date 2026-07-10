"""Full-chain observability: telemetry ingest, per-LLM-turn metrics, and the
admin metrics/replay readers.

All writers are BEST-EFFORT and no-op when there is no database -- callers must
never let an analytics failure break a build or an LLM stream. The single source
of truth for "is there a DB" is `_db_enabled()`; every public writer early-returns
on it so local/stub/non-db-test runs stay clean.

Ported from the frozen plugin backend (cursor_for_hardware/mpyhw-api/app/analytics.py)
and adapted to the active codebase: the event vocabulary is the browser's real
`onEvent`/`onTimeline.raw` types (NOT the plugin's), and the live-concurrency signal
comes from the in-process limiter in app.api.llm (there is no llm_sessions module here).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from app import db

logger = logging.getLogger("blockless.analytics")


# keep in sync with the browser onEvent / onTimeline.raw types emitted in
# website-blockless/src/blockless/browserBuild.js + ide-src/src/blockless_protocol_client.js
ALLOWED_EVENT_TYPES = {
    "session_start",
    "phase_start",
    "assistant_text_delta",
    "assistant_text",
    "tool_use_complete",
    "status_update",
    "phase_complete",
    "phase_error",
    "phase_stalled",
    "file_written",
    "manifest_updated",
    "storage_degraded",  # browser emits this when IndexedDB is unavailable (private browsing)
    "device_error",
    "serial_output",
    "credits",
    "service_waiting",
    "session_error",
    "session_expired",
    "session_finished",
}

# Telemetry is stored with a per-field size bound: an oversized field (a serial flood,
# a big preview) is truncated and flagged `_truncated` rather than dropped. Backstop to
# the client-side bound in telemetry.js; the route still enforces a whole-batch limit.
FIELD_BYTE_BUDGET = 48 * 1024

ingestion_failure_count = 0


def _db_enabled() -> bool:
    return bool(os.getenv("DATABASE_URL"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- writers (best-effort; no-op without a DB) ------------------------------


def record_telemetry(events: list[dict[str, Any]]) -> None:
    if not _db_enabled():
        return
    from psycopg.types.json import Jsonb

    now = _now()
    with db.connect() as conn:
        try:
            for event in events:
                payload = sanitize_payload(event.get("payload") or {})
                db.execute(
                    conn,
                    "INSERT INTO telemetry_events(trace_id, user_id, event_type, timestamp, payload_json, created_at) VALUES(?,?,?,?,?,?)",
                    (
                        event["trace_id"],
                        event.get("user_id"),
                        event["event_type"],
                        event["timestamp"],
                        Jsonb(payload),
                        now,
                    ),
                )
                _update_session(conn, event, payload)
            conn.commit()
        except Exception:
            conn.rollback()
            global ingestion_failure_count
            ingestion_failure_count += 1
            logger.warning("telemetry ingestion failed; rolled back", exc_info=True)
            raise


def record_llm_turn(
    *,
    trace_id: str | None,
    user_id: str | None,
    kind: str,
    model: str | None,
    started_at: datetime,
    duration_ms: int | None,
    input_tokens: int | None,
    output_tokens: int | None,
    total_tokens: int | None,
    credits_charged: int | None,
    status: str,
    error_kind: str | None = None,
) -> None:
    """Record one LLM turn. `duration_ms` is supplied by the caller (computed from a
    monotonic clock, not wall-clock subtraction, to survive NTP adjustments); started_at
    is stored only as a timestamp."""
    if not _db_enabled():
        return
    with db.connect() as conn:
        db.execute(
            conn,
            """
            INSERT INTO llm_turns(
                trace_id, user_id, kind, model, started_at, ended_at, duration_ms,
                input_tokens, output_tokens, total_tokens, credits_charged, status, error_kind
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                trace_id,
                user_id,
                kind,
                model,
                started_at.isoformat(),
                _now(),
                duration_ms,
                input_tokens,
                output_tokens,
                total_tokens,
                credits_charged,
                status,
                error_kind,
            ),
        )
        conn.commit()


# --- payload size guard -----------------------------------------------------


def sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    guarded, truncated = _guard_size(payload)
    if truncated:
        guarded["_truncated"] = True
    return guarded


def _guard_size(value: Any) -> tuple[Any, bool]:
    if isinstance(value, str):
        if len(value.encode("utf-8")) > FIELD_BYTE_BUDGET:
            return value.encode("utf-8")[:FIELD_BYTE_BUDGET].decode("utf-8", "ignore"), True
        return value, False
    if isinstance(value, list):
        kept: list[Any] = []
        truncated = False
        size = 0
        for element in reversed(value):  # keep the tail; recent lines matter most
            guarded, element_truncated = _guard_size(element)
            truncated = truncated or element_truncated
            length = len(json.dumps(guarded, ensure_ascii=False, default=str).encode("utf-8"))
            if size + length > FIELD_BYTE_BUDGET and kept:
                truncated = True
                break
            kept.insert(0, guarded)
            size += length
        return kept, truncated
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        truncated = False
        for key, inner in value.items():
            guarded, inner_truncated = _guard_size(inner)
            out[key] = guarded
            truncated = truncated or inner_truncated
        return out, truncated
    return value, False


# --- readers (back the admin replay) ----------------------------------------


def telemetry_events(*, trace_id: str) -> list[dict[str, Any]]:
    if not _db_enabled():
        return []
    with db.connect() as conn:
        rows = db.fetchall(
            conn,
            "SELECT event_type, payload_json, user_id, timestamp FROM telemetry_events WHERE trace_id=? ORDER BY id",
            (trace_id,),
        )
    return [
        {"event_type": row["event_type"], "payload": _json(row["payload_json"]), "user_id": row["user_id"], "timestamp": row["timestamp"]}
        for row in rows
    ]


def llm_turns_for(*, trace_id: str) -> list[dict[str, Any]]:
    if not _db_enabled():
        return []
    with db.connect() as conn:
        return db.fetchall(
            conn,
            """
            SELECT kind, model, status, error_kind, input_tokens, output_tokens, total_tokens,
                   credits_charged, duration_ms, started_at, ended_at
            FROM llm_turns WHERE trace_id=? ORDER BY id
            """,
            (trace_id,),
        )


def session_for(*, trace_id: str) -> dict[str, Any] | None:
    if not _db_enabled():
        return None
    with db.connect() as conn:
        return db.fetchone(conn, "SELECT * FROM sessions WHERE trace_id=?", (trace_id,))


# --- metrics ----------------------------------------------------------------


def metrics_snapshot() -> dict[str, Any]:
    if not _db_enabled():
        return {"db": "unavailable"}
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    with db.connect() as conn:
        llm_durations = [row["duration_ms"] for row in db.fetchall(conn, "SELECT duration_ms FROM llm_turns WHERE duration_ms IS NOT NULL")]
        session_durations = [
            row["duration_ms"]
            for row in db.fetchall(
                conn,
                """
                SELECT CAST(EXTRACT(EPOCH FROM (ended_at::timestamptz - started_at::timestamptz)) * 1000 AS INTEGER) AS duration_ms
                FROM sessions WHERE ended_at IS NOT NULL
                """,
            )
        ]
        terminal_distribution = _counts(
            conn,
            "SELECT COALESCE(terminal, 'active') AS key, COUNT(*) AS count FROM sessions GROUP BY COALESCE(terminal, 'active')",
        )
        event_counts = _counts(conn, "SELECT event_type AS key, COUNT(*) AS count FROM telemetry_events GROUP BY event_type")
        tokens_session = db.fetchone(conn, "SELECT AVG(total_tokens) AS avg FROM llm_turns WHERE total_tokens IS NOT NULL")["avg"]
        credits_session = db.fetchone(conn, "SELECT AVG(credits_charged) AS avg FROM llm_turns WHERE credits_charged IS NOT NULL")["avg"]
        credits_day = db.fetchone(
            conn,
            """
            SELECT AVG(spent) AS avg FROM (
                SELECT user_id, created_at::date AS day, SUM(-credits) AS spent
                FROM credit_ledger
                WHERE credits < 0 AND action <> 'admin_set'
                GROUP BY user_id, created_at::date
            ) user_days
            """,
        )["avg"]
        daily_active_users = db.fetchone(conn, "SELECT COUNT(*) AS count FROM users WHERE last_seen_at::timestamptz >= ?::timestamptz", (day_start,))["count"]
        new_users_day = db.fetchone(conn, "SELECT COUNT(*) AS count FROM users WHERE created_at::timestamptz >= ?::timestamptz", (day_start,))["count"]
        llm_error_count = db.fetchone(conn, "SELECT COUNT(*) AS count FROM llm_turns WHERE status='error'")["count"]
        llm_total_count = db.fetchone(conn, "SELECT COUNT(*) AS count FROM llm_turns")["count"]
    return {
        "active_llm_streams": _limiter_snapshot(),
        "llm_turn_duration_ms": _percentiles(llm_durations),
        "session_duration_ms": _percentiles(session_durations, include_p99=False),
        "llm_error_rate": _rate(llm_error_count, llm_total_count - llm_error_count),
        "tokens_per_session": tokens_session or 0,
        "credits_per_session": credits_session or 0,
        "credits_per_user_day": credits_day or 0,
        "phase_error_rate": _rate(event_counts.get("phase_error", 0), event_counts.get("phase_complete", 0)),
        "device_error_rate": _rate(event_counts.get("device_error", 0), event_counts.get("session_finished", 0)),
        "stall_rate": _rate(event_counts.get("phase_stalled", 0), event_counts.get("session_start", 0)),
        "session_terminal_distribution": terminal_distribution,
        "postgres_write_failure_count": db.write_failure_count,
        "telemetry_ingestion_failure_count": ingestion_failure_count,
        "daily_active_users": daily_active_users,
        "new_users_day": new_users_day,
        "activation_funnel": {
            "session_start": event_counts.get("session_start", 0),
            "phase_start": event_counts.get("phase_start", 0),
            "phase_complete": event_counts.get("phase_complete", 0),
            "manifest_updated": event_counts.get("manifest_updated", 0),
            "file_written": event_counts.get("file_written", 0),
            "session_finished": event_counts.get("session_finished", 0),
        },
    }


def _limiter_snapshot() -> dict[str, Any]:
    # Lazy import to avoid a circular import (app.api.llm imports this module).
    try:
        from app.api.llm import _limiter

        return _limiter.snapshot()
    except Exception:  # pragma: no cover - never let metrics crash on the limiter
        return {}


# --- session aggregate ------------------------------------------------------


def _update_session(conn: Any, event: dict[str, Any], payload: dict[str, Any]) -> None:
    event_type = event["event_type"]
    trace_id = event["trace_id"]
    user_id = event.get("user_id")
    if event_type == "session_start":
        db.execute(
            conn,
            """
            INSERT INTO sessions(trace_id, user_id, board_id, intent_hash, started_at, turn_count, repair_count)
            VALUES(?,?,?,?,?,0,0)
            ON CONFLICT(trace_id) DO UPDATE SET user_id=excluded.user_id, board_id=excluded.board_id, intent_hash=excluded.intent_hash
            """,
            (trace_id, user_id, payload.get("board_id"), payload.get("intent_hash"), event["timestamp"]),
        )
    elif event_type in {"session_finished", "session_error", "session_expired"}:
        terminal = payload.get("terminal") or event_type
        db.execute(
            conn,
            "UPDATE sessions SET ended_at=?, terminal=? WHERE trace_id=?",
            (event["timestamp"], terminal, trace_id),
        )
    elif event_type == "phase_start":
        db.execute(conn, "UPDATE sessions SET turn_count=turn_count + 1 WHERE trace_id=?", (trace_id,))
    elif event_type in {"phase_error", "phase_stalled"}:
        db.execute(conn, "UPDATE sessions SET repair_count=repair_count + 1 WHERE trace_id=?", (trace_id,))


# --- helpers ----------------------------------------------------------------


def _counts(conn: Any, sql: str) -> dict[str, int]:
    return {row["key"]: row["count"] for row in db.fetchall(conn, sql)}


def _rate(success: int, other: int) -> float:
    total = success + other
    return success / total if total else 0.0


def _percentiles(values: list[int], *, include_p99: bool = True) -> dict[str, int | None]:
    values = sorted(value for value in values if value is not None)
    out = {"p50": _percentile(values, 50), "p95": _percentile(values, 95)}
    if include_p99:
        out["p99"] = _percentile(values, 99)
    return out


def _percentile(values: list[int], percent: int) -> int | None:
    if not values:
        return None
    index = min(len(values) - 1, round((percent / 100) * (len(values) - 1)))
    return values[index]


def _json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return json.loads(value)
