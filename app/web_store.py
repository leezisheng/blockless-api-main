"""Persistence for the anonymous website data-capture endpoints (newsletter signups +
generated website-to-IDE recipes).

Kept separate from the in-product agent telemetry namespace (telemetry_events): website
marketing data must not pollute the product funnel.

Writes are FAIL-LOUD: a DB error propagates so a failure is never silently hidden (the
owner's no-silent-fallback rule). These endpoints therefore require a reachable database.
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any

from app import db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_newsletter_signup(email: str, locale: str, source: str) -> None:
    """Persist one newsletter signup (idempotent on the normalized email). Raises on a DB
    failure so the caller surfaces it rather than dropping the lead silently."""
    normalized = email.strip().lower()
    with db.connect() as conn:
        db.execute(
            conn,
            "INSERT INTO newsletter_subscribers(email, locale, source, created_at) "
            "VALUES(?,?,?,?) ON CONFLICT(email) DO NOTHING",
            (normalized, locale, source, _now()),
        )
        conn.commit()


def record_web_recipe(recipe: dict[str, Any]) -> str:
    """Persist a generated website-to-IDE recipe and return its public id. Raises on a DB
    failure -- the recommend route must not hand back a recipe_id that can't be loaded."""
    from psycopg.types.json import Jsonb

    recipe_id = f"rec_{uuid.uuid4().hex[:12]}"
    payload = copy.deepcopy(recipe or {})
    payload["recipe_id"] = recipe_id
    with db.connect() as conn:
        db.execute(
            conn,
            "INSERT INTO web_recipes(id, recipe_json, created_at) VALUES(?,?,?)",
            (recipe_id, Jsonb(payload), _now()),
        )
        conn.commit()
    return recipe_id


def load_web_recipe(recipe_id: str) -> dict[str, Any] | None:
    """Load a stored recipe, or None when no such recipe exists. A DB error propagates
    (surfaced as 5xx) rather than masquerading as a 404 not-found."""
    with db.connect() as conn:
        row = db.fetchone(conn, "SELECT recipe_json FROM web_recipes WHERE id=?", (recipe_id,))
    if not row:
        return None
    recipe = row["recipe_json"]
    return copy.deepcopy(recipe) if isinstance(recipe, dict) else None
