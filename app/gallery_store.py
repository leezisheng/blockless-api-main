"""Persistence for the public Gallery — publish / browse / like / comment / remix.

Fail-loud, mirroring `web_store`/`credit_store`. Public reads (list/detail/comments) need no
auth; writes (publish/like/comment/remix) carry the session user and upsert it first. Like and
remix counts are kept on the publication row in the SAME transaction as the like/remix insert
(the publication row is locked FOR UPDATE) so concurrent actions can't drift the counters.
"""
from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any

from app import db, project_store


class PublicationNotFound(Exception):
    """No gallery publication with that id. Routers map it to 404."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _publication_id() -> str:
    return f"pub_{uuid.uuid4().hex[:12]}"


def _comment_id() -> str:
    return f"cmt_{uuid.uuid4().hex[:12]}"


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    pub = dict(row)
    for key in ("parts_json", "tags_json", "snapshot_json"):
        value = pub.get(key)
        if isinstance(value, (dict, list)):
            pub[key] = copy.deepcopy(value)
    return pub


def publish(
    user: dict[str, Any],
    *,
    project_id: str,
    title: str,
    description: str | None,
    icon: str | None,
    tags: list[str],
    parts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Publish one of the caller's own projects to the Gallery.

    The build snapshot and board are read authoritatively from the owned project row (not
    trusted from the client). Raises project_store.ProjectNotFound when the project is missing
    or not owned by the caller.
    """
    from psycopg.types.json import Jsonb

    now = _now()
    pub_id = _publication_id()
    with db.connect() as conn:
        try:
            db.upsert_user(conn, user, now)
            project = db.fetchone(
                conn,
                "SELECT board_id, snapshot_json FROM projects WHERE id=? AND owner_id=?",
                (project_id, str(user["id"])),
            )
            if project is None:
                conn.rollback()
                raise project_store.ProjectNotFound(project_id)
            snapshot = project["snapshot_json"] or {}
            db.execute(
                conn,
                "INSERT INTO gallery_publications(id, project_id, owner_id, login, title, "
                "description, icon, board_id, parts_json, tags_json, snapshot_json, like_count, "
                "remix_count, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,0,0,?)",
                (
                    pub_id,
                    project_id,
                    str(user["id"]),
                    user.get("login"),
                    title,
                    description,
                    icon,
                    project["board_id"],
                    Jsonb(parts or []),
                    Jsonb(tags or []),
                    Jsonb(snapshot),
                    now,
                ),
            )
            row = db.fetchone(conn, "SELECT * FROM gallery_publications WHERE id=?", (pub_id,))
            conn.commit()
        except project_store.ProjectNotFound:
            raise
        except Exception:
            conn.rollback()
            raise
    return _clean(row)


def list_publications(*, tag: str | None = None, limit: int = 60) -> list[dict[str, Any]]:
    """Newest-first list for the Gallery + Home. Optional tag filter via JSONB containment."""
    from psycopg.types.json import Jsonb

    limit = max(1, min(int(limit), 200))
    with db.connect() as conn:
        if tag:
            rows = db.fetchall(
                conn,
                "SELECT * FROM gallery_publications WHERE tags_json @> ? "
                "ORDER BY created_at DESC LIMIT ?",
                (Jsonb([tag]), limit),
            )
        else:
            rows = db.fetchall(
                conn,
                "SELECT * FROM gallery_publications ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
    return [_clean(row) for row in rows]


def get_publication(publication_id: str) -> dict[str, Any]:
    with db.connect() as conn:
        row = db.fetchone(
            conn, "SELECT * FROM gallery_publications WHERE id=?", (publication_id,)
        )
    if row is None:
        raise PublicationNotFound(publication_id)
    return _clean(row)


def toggle_like(user: dict[str, Any], publication_id: str) -> dict[str, Any]:
    """Idempotent like toggle. Returns {liked, like_count}. The publication row is locked
    FOR UPDATE so the counter stays exact under concurrency."""
    now = _now()
    with db.connect() as conn:
        try:
            db.upsert_user(conn, user, now)
            pub = db.fetchone(
                conn,
                "SELECT like_count FROM gallery_publications WHERE id=? FOR UPDATE",
                (publication_id,),
            )
            if pub is None:
                conn.rollback()
                raise PublicationNotFound(publication_id)
            existing = db.fetchone(
                conn,
                "SELECT 1 FROM gallery_likes WHERE publication_id=? AND user_id=?",
                (publication_id, str(user["id"])),
            )
            if existing:
                db.execute(
                    conn,
                    "DELETE FROM gallery_likes WHERE publication_id=? AND user_id=?",
                    (publication_id, str(user["id"])),
                )
                db.execute(
                    conn,
                    "UPDATE gallery_publications SET like_count = GREATEST(0, like_count - 1) WHERE id=?",
                    (publication_id,),
                )
                liked = False
            else:
                db.execute(
                    conn,
                    "INSERT INTO gallery_likes(publication_id, user_id, created_at) VALUES(?,?,?)",
                    (publication_id, str(user["id"]), now),
                )
                db.execute(
                    conn,
                    "UPDATE gallery_publications SET like_count = like_count + 1 WHERE id=?",
                    (publication_id,),
                )
                liked = True
            row = db.fetchone(
                conn, "SELECT like_count FROM gallery_publications WHERE id=?", (publication_id,)
            )
            conn.commit()
        except PublicationNotFound:
            raise
        except Exception:
            conn.rollback()
            raise
    return {"liked": liked, "like_count": row["like_count"]}


def list_comments(publication_id: str) -> list[dict[str, Any]]:
    with db.connect() as conn:
        # A read shouldn't 200 with an empty list for a publication that doesn't exist.
        pub = db.fetchone(
            conn, "SELECT 1 FROM gallery_publications WHERE id=?", (publication_id,)
        )
        if pub is None:
            raise PublicationNotFound(publication_id)
        rows = db.fetchall(
            conn,
            "SELECT id, publication_id, user_id, login, body, created_at FROM gallery_comments "
            "WHERE publication_id=? ORDER BY id ASC",
            (publication_id,),
        )
    return [dict(row) for row in rows]


def add_comment(user: dict[str, Any], publication_id: str, body: str) -> dict[str, Any]:
    now = _now()
    comment_id = _comment_id()
    with db.connect() as conn:
        try:
            db.upsert_user(conn, user, now)
            pub = db.fetchone(
                conn, "SELECT 1 FROM gallery_publications WHERE id=?", (publication_id,)
            )
            if pub is None:
                conn.rollback()
                raise PublicationNotFound(publication_id)
            db.execute(
                conn,
                "INSERT INTO gallery_comments(publication_id, user_id, login, body, created_at) "
                "VALUES(?,?,?,?,?)",
                (publication_id, str(user["id"]), user.get("login"), body, now),
            )
            row = db.fetchone(
                conn,
                "SELECT id, publication_id, user_id, login, body, created_at FROM gallery_comments "
                "WHERE publication_id=? AND user_id=? ORDER BY id DESC LIMIT 1",
                (publication_id, str(user["id"])),
            )
            conn.commit()
        except PublicationNotFound:
            raise
        except Exception:
            conn.rollback()
            raise
    return dict(row)


def remix(user: dict[str, Any], publication_id: str) -> dict[str, Any]:
    """Fork a published build into a NEW draft project owned by the caller, and bump the
    source publication's remix_count in the same transaction."""
    now = _now()
    with db.connect() as conn:
        try:
            pub = db.fetchone(
                conn,
                "SELECT title, icon, board_id, snapshot_json FROM gallery_publications "
                "WHERE id=? FOR UPDATE",
                (publication_id,),
            )
            if pub is None:
                conn.rollback()
                raise PublicationNotFound(publication_id)
            project = project_store.insert_project(
                conn,
                user=user,
                title=pub["title"],
                icon=pub["icon"],
                board_id=pub["board_id"],
                status="draft",
                snapshot=pub["snapshot_json"] or {},
                conversation=None,
                remixed_from=publication_id,
                now=now,
            )
            db.execute(
                conn,
                "UPDATE gallery_publications SET remix_count = remix_count + 1 WHERE id=?",
                (publication_id,),
            )
            conn.commit()
        except PublicationNotFound:
            raise
        except Exception:
            conn.rollback()
            raise
    return project
