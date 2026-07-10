from __future__ import annotations

import os
from typing import Any


def client_ip(request: Any) -> str:
    """Best-effort real client IP for per-IP rate limiting.

    Behind Render's proxy, `request.client.host` is the proxy address -- so every user
    shares one limiter bucket and the per-IP limits are meaningless. When
    MPYHW_TRUST_PROXY_HEADERS=1 (set in the Render env, where exactly one trusted proxy
    fronts the app), trust the proxy-appended hop of X-Forwarded-For instead.

    Off by default on purpose: trusting X-Forwarded-For when the app is NOT behind a trusted
    proxy lets any client spoof the header and dodge the limiter.

    Render APPENDS the real client IP to any client-supplied X-Forwarded-For (it does not
    overwrite), so the RIGHTMOST entry is the hop Render added and the leftmost is attacker-
    controlled. Trust the rightmost non-empty entry; fall back to the socket peer if there is none.
    """
    if os.getenv("MPYHW_TRUST_PROXY_HEADERS") == "1":
        headers = getattr(request, "headers", None)
        forwarded = headers.get("x-forwarded-for") if headers is not None else None
        if forwarded:
            for part in reversed(forwarded.split(",")):
                candidate = part.strip()
                if candidate:
                    return candidate
    client = getattr(request, "client", None)
    return getattr(client, "host", None) or "unknown"
