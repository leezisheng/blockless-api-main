"""Persistence for saved builds — the Dashboard's "My projects".

Fail-loud, mirroring `web_store`/`credit_store`: a DB error propagates so a save is never
silently dropped (the owner's no-silent-fallback rule). Ownership is enforced in SQL with
`WHERE owner_id=?` (the schema is FK-free); a non-owner gets the same 404 as a missing row,
so project existence is never leaked across accounts.
"""
from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any

from app import db


# Build lifecycle, mirrored by the UI badges (draft -> simulated -> awaiting_parts -> on_device).
ALLOWED_STATUS = {"draft", "simulated", "awaiting_parts", "on_device"}


class ProjectNotFound(Exception):
    """No project with that id owned by the caller. Routers map it to 404."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_id() -> str:
    return f"proj_{uuid.uuid4().hex[:12]}"


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    """Deep-copy the JSONB columns so a caller can't mutate a pooled/cached object."""
    project = dict(row)
    for key in ("snapshot_json", "conversation_json"):
        value = project.get(key)
        if isinstance(value, (dict, list)):
            project[key] = copy.deepcopy(value)
    return project


def insert_project(
    conn: Any,
    *,
    user: dict[str, Any],
    title: str,
    icon: str | None,
    board_id: str | None,
    status: str,
    snapshot: dict[str, Any] | None,
    conversation: Any,
    remixed_from: str | None,
    now: str,
) -> dict[str, Any]:
    """Insert one project in the caller's transaction (no commit) and return its row dict.

    Shared by `create_project` (own connection + commit) and `gallery_store.remix`, which
    inserts the remixed copy and bumps the source's remix_count in a single transaction.
    Upserts the JWT user first so a brand-new user who saves before ever touching credits
    still has a `users` row.
    """
    from psycopg.types.json import Jsonb

    project_id = _project_id()
    db.upsert_user(conn, user, now)
    db.execute(
        conn,
        "INSERT INTO projects(id, owner_id, title, icon, board_id, status, snapshot_json, "
        "conversation_json, remixed_from, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            project_id,
            str(user["id"]),
            title,
            icon,
            board_id,
            status,
            Jsonb(snapshot or {}),
            Jsonb(conversation) if conversation is not None else None,
            remixed_from,
            now,
            now,
        ),
    )
    return {
        "id": project_id,
        "owner_id": str(user["id"]),
        "title": title,
        "icon": icon,
        "board_id": board_id,
        "status": status,
        "snapshot_json": copy.deepcopy(snapshot or {}),
        "conversation_json": copy.deepcopy(conversation) if conversation is not None else None,
        "remixed_from": remixed_from,
        "created_at": now,
        "updated_at": now,
    }


def create_project(
    user: dict[str, Any],
    *,
    title: str,
    icon: str | None = None,
    board_id: str | None = None,
    status: str = "draft",
    snapshot: dict[str, Any] | None = None,
    conversation: Any = None,
    remixed_from: str | None = None,
) -> dict[str, Any]:
    if status not in ALLOWED_STATUS:
        raise ValueError(f"invalid status: {status}")
    now = _now()
    with db.connect() as conn:
        try:
            project = insert_project(
                conn,
                user=user,
                title=title,
                icon=icon,
                board_id=board_id,
                status=status,
                snapshot=snapshot,
                conversation=conversation,
                remixed_from=remixed_from,
                now=now,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return project


def update_project(
    user: dict[str, Any],
    project_id: str,
    *,
    title: str | None = None,
    icon: str | None = None,
    board_id: str | None = None,
    status: str | None = None,
    snapshot: dict[str, Any] | None = None,
    conversation: Any = None,
) -> dict[str, Any]:
    """Ownership-checked partial update of the mutable fields; always bumps updated_at.

    Only non-None arguments are written. Raises ProjectNotFound when the row is missing or
    owned by someone else (same 404 either way -- no cross-account existence leak)."""
    from psycopg.types.json import Jsonb

    if status is not None and status not in ALLOWED_STATUS:
        raise ValueError(f"invalid status: {status}")
    now = _now()
    sets = ["updated_at=?"]
    params: list[Any] = [now]
    if title is not None:
        sets.append("title=?"); params.append(title)
    if icon is not None:
        sets.append("icon=?"); params.append(icon)
    if board_id is not None:
        sets.append("board_id=?"); params.append(board_id)
    if status is not None:
        sets.append("status=?"); params.append(status)
    if snapshot is not None:
        sets.append("snapshot_json=?"); params.append(Jsonb(snapshot))
    if conversation is not None:
        sets.append("conversation_json=?"); params.append(Jsonb(conversation))
    params.extend([project_id, str(user["id"])])
    with db.connect() as conn:
        try:
            result = db.execute(
                conn,
                f"UPDATE projects SET {', '.join(sets)} WHERE id=? AND owner_id=?",
                tuple(params),
            )
            if result.rowcount != 1:
                conn.rollback()
                raise ProjectNotFound(project_id)
            row = db.fetchone(conn, "SELECT * FROM projects WHERE id=?", (project_id,))
            conn.commit()
        except ProjectNotFound:
            raise
        except Exception:
            conn.rollback()
            raise
    return _clean(row)


def delete_project(user: dict[str, Any], project_id: str) -> None:
    with db.connect() as conn:
        try:
            result = db.execute(
                conn,
                "DELETE FROM projects WHERE id=? AND owner_id=?",
                (project_id, str(user["id"])),
            )
            if result.rowcount != 1:
                conn.rollback()
                raise ProjectNotFound(project_id)
            conn.commit()
        except ProjectNotFound:
            raise
        except Exception:
            conn.rollback()
            raise


def list_projects(user: dict[str, Any]) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = db.fetchall(
            conn,
            "SELECT * FROM projects WHERE owner_id=? ORDER BY updated_at DESC",
            (str(user["id"]),),
        )
    return [_clean(row) for row in rows]


def get_project(user: dict[str, Any], project_id: str) -> dict[str, Any]:
    """Load one project owned by the caller, or raise ProjectNotFound."""
    with db.connect() as conn:
        row = db.fetchone(
            conn,
            "SELECT * FROM projects WHERE id=? AND owner_id=?",
            (project_id, str(user["id"])),
        )
    if row is None:
        raise ProjectNotFound(project_id)
    return _clean(row)
