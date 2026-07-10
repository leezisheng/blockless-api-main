"""Smoke tests for the health endpoints."""
from __future__ import annotations


def test_health_ok(client) -> None:
    response = client.get("/v1/health")
    assert response.status_code == 200


def test_build_capabilities_shape(client) -> None:
    response = client.get("/v1/build/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert "tools" in body
    assert isinstance(body["browser_validate"], list)
