from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger("mpyhw.db")

_initialized: set[str] = set()
write_failure_count = 0


def _database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    if not _is_postgres(url):
        raise RuntimeError("DATABASE_URL must be a postgres:// or postgresql:// URL")
    return url


def _is_postgres(url: str) -> bool:
    return url.startswith("postgres://") or url.startswith("postgresql://")


_pool: Any = None
_pool_lock = threading.Lock()


def _get_pool() -> Any:
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            url = _database_url()
            initialize()
            pool = ConnectionPool(
                url,
                min_size=1,
                max_size=int(os.getenv("MPYHW_DB_POOL_MAX", "10")),
                kwargs={"row_factory": dict_row},
                open=False,
            )
            pool.open()
            _pool = pool
    return _pool


@contextmanager
def connect() -> Iterator[Any]:
    # Check a connection out of the pool instead of paying a fresh connect handshake on
    # every call (one LLM turn makes several credit calls). psycopg_pool's context manager
    # commits on a clean exit, rolls back on exception, and resets the connection before
    # returning it to the pool -- so callers keep their explicit commit/rollback and no open
    # transaction or FOR UPDATE lock can leak to the next checkout.
    with _get_pool().connection() as conn:
        yield conn


def open_pool() -> None:
    """Warm the pool at app startup. Lazy _get_pool covers everything else; this just opens
    the first connection eagerly from the lifespan."""
    _get_pool()


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


def execute(conn: Any, sql: str, params: tuple[Any, ...] = ()):
    try:
        return conn.execute(_sql(sql), params)
    except Exception:
        global write_failure_count
        if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE")):
            write_failure_count += 1
            logger.warning("db write failed", exc_info=True)
        raise


def fetchone(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    row = execute(conn, sql, params).fetchone()
    if row is None:
        return None
    return dict(row)


def fetchall(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in execute(conn, sql, params).fetchall()]


def upsert_user(conn: Any, user: dict[str, Any], now_iso: str) -> None:
    """Ensure a `users` row exists for the session-JWT user, in the caller's transaction.

    `get_current_user` only decodes the JWT -- it never writes a row. Credit flow upserts
    the user lazily, but a brand-new user can hit a social endpoint (save a project, publish)
    before ever touching credits. The owner_id columns are FK-free, so a missing row wouldn't
    break the insert, but we keep `users` authoritative for login/email joins. Race-safe:
    `ON CONFLICT DO NOTHING` ignores both unique constraints (id PK, gh_user_id), then the
    UPDATE refreshes the mutable fields whether the row was just inserted or already existed.
    """
    uid = str(user["id"])
    execute(
        conn,
        "INSERT INTO users(id, gh_user_id, login, email, created_at, last_seen_at) "
        "VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING",
        (uid, uid, user.get("login"), user.get("email"), now_iso, now_iso),
    )
    execute(
        conn,
        "UPDATE users SET login=COALESCE(?, login), email=COALESCE(?, email), last_seen_at=? WHERE id=?",
        (user.get("login"), user.get("email"), now_iso, uid),
    )


_readiness_lock = threading.Lock()
_readiness_conn: Any = None


def ping() -> None:
    """Cheap readiness check: confirm the DB is reachable. Raises on failure.

    The readiness probe fires every ~15s, so reuse one lazily-created connection
    instead of paying a fresh connect handshake each time. A dropped/stale connection
    is transparently reconnected once before the failure propagates. The probe route
    is sync (threadpool) and this is lock-guarded, so the shared connection is only
    ever touched by one caller at a time."""
    global _readiness_conn
    import psycopg

    with _readiness_lock:
        for attempt in range(2):
            try:
                if _readiness_conn is None or _readiness_conn.closed:
                    initialize()
                    _readiness_conn = psycopg.connect(_database_url())
                _readiness_conn.execute("SELECT 1")
                _readiness_conn.commit()
                return
            except Exception:
                if _readiness_conn is not None:
                    try:
                        _readiness_conn.close()
                    except Exception:
                        pass
                    _readiness_conn = None
                if attempt == 1:
                    raise


def _sql(sql: str) -> str:
    return sql.replace("?", "%s")


def initialize() -> None:
    url = _database_url()
    if url in _initialized:
        return
    _initialize_postgres(url)
    _initialized.add(url)


def _initialize_postgres(url: str) -> None:
    import psycopg

    conn = psycopg.connect(url)
    try:
        for statement in _schema():
            conn.execute(statement)
        conn.commit()
    finally:
        conn.close()


def _schema() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            gh_user_id TEXT UNIQUE,
            login TEXT,
            email TEXT,
            created_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS credit_balances (
            user_id TEXT PRIMARY KEY,
            balance INTEGER NOT NULL,
            daily_grant INTEGER NOT NULL,
            last_grant_date TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS credit_ledger (
            id BIGSERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            action TEXT NOT NULL,
            credits INTEGER NOT NULL,
            balance_after INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS token_tallies (
            user_id TEXT PRIMARY KEY,
            total_tokens INTEGER NOT NULL,
            last_tally_date TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS daily_global_spend (
            spend_date TEXT PRIMARY KEY,
            credits_spent INTEGER NOT NULL
        )
        """,
        # Website marketing data, deliberately separate from the product namespace. Only the
        # two tables with live writers remain (newsletter signups + generated recipes); the
        # telemetry/session/upload/quote/event tables were dropped with their dead writers.
        """
        CREATE TABLE IF NOT EXISTS newsletter_subscribers (
            email TEXT PRIMARY KEY,
            locale TEXT,
            source TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS web_recipes (
            id TEXT PRIMARY KEY,
            recipe_json JSONB NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        # Full-chain observability: one build is keyed by trace_id across all three tables.
        # telemetry_events = raw replayable browser event trace; llm_turns = per-turn LLM
        # metrics; sessions = per-build aggregate. Best-effort writers (app/analytics.py)
        # no-op when DATABASE_URL is unset.
        """
        CREATE TABLE IF NOT EXISTS telemetry_events (
            id BIGSERIAL PRIMARY KEY,
            trace_id TEXT NOT NULL,
            user_id TEXT,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            payload_json JSONB NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_telemetry_trace ON telemetry_events(trace_id)",
        "CREATE INDEX IF NOT EXISTS idx_telemetry_type ON telemetry_events(event_type)",
        "CREATE INDEX IF NOT EXISTS idx_telemetry_created ON telemetry_events(created_at)",
        """
        CREATE TABLE IF NOT EXISTS llm_turns (
            id BIGSERIAL PRIMARY KEY,
            trace_id TEXT,
            user_id TEXT,
            kind TEXT NOT NULL,
            model TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            duration_ms INTEGER,
            input_tokens INTEGER,
            output_tokens INTEGER,
            total_tokens INTEGER,
            credits_charged INTEGER,
            status TEXT NOT NULL,
            error_kind TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_llm_turns_user ON llm_turns(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_llm_turns_trace ON llm_turns(trace_id)",
        "CREATE INDEX IF NOT EXISTS idx_llm_turns_started ON llm_turns(started_at)",
        """
        CREATE TABLE IF NOT EXISTS sessions (
            trace_id TEXT PRIMARY KEY,
            user_id TEXT,
            board_id TEXT,
            intent_hash TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            terminal TEXT,
            turn_count INTEGER NOT NULL DEFAULT 0,
            repair_count INTEGER NOT NULL DEFAULT 0
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)",
        # Social product layer: saved builds (Dashboard) + the public Gallery (publish /
        # remix / likes / comments). owner_id is users.id from the session JWT. No FK
        # constraints (the rest of the schema is FK-free); ownership is enforced in the
        # store with `WHERE owner_id=?`. snapshot_json holds the build artifacts
        # (code/board/wiring/manifest); conversation_json holds the saved chat timeline.
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            title TEXT NOT NULL,
            icon TEXT,
            board_id TEXT,
            status TEXT NOT NULL,
            snapshot_json JSONB NOT NULL,
            conversation_json JSONB,
            remixed_from TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id)",
        """
        CREATE TABLE IF NOT EXISTS gallery_publications (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            login TEXT,
            title TEXT NOT NULL,
            description TEXT,
            icon TEXT,
            board_id TEXT,
            parts_json JSONB NOT NULL,
            tags_json JSONB NOT NULL,
            snapshot_json JSONB NOT NULL,
            like_count INTEGER NOT NULL DEFAULT 0,
            remix_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_gallery_created ON gallery_publications(created_at)",
        """
        CREATE TABLE IF NOT EXISTS gallery_likes (
            publication_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (publication_id, user_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS gallery_comments (
            id BIGSERIAL PRIMARY KEY,
            publication_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            login TEXT,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_gallery_comments_pub ON gallery_comments(publication_id)",
    ]


def reset_for_tests() -> None:
    global _readiness_conn
    _initialized.clear()
    close_pool()
    if _readiness_conn is not None:
        try:
            _readiness_conn.close()
        except Exception:
            pass
        _readiness_conn = None
