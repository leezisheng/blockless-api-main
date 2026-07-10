from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BROWSER_SKILLS_ROOT = REPO_ROOT / "third_party" / "browser-micropython-skills"


def cors_origins() -> list[str]:
    configured = os.getenv("MPYHW_CORS_ORIGINS")
    defaults = [
        "https://block-less.com",
        "https://www.block-less.com",
        "https://blockless.co",
        "https://www.blockless.co",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8098",
        "http://127.0.0.1:8098",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    if configured is None:
        return defaults
    origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    return origins or defaults

