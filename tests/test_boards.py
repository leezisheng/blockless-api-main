"""Board listing tests."""
from __future__ import annotations


def test_boards_listing(client) -> None:
    response = client.get("/v1/boards")
    assert response.status_code == 200
    body = response.json()
    assert "builtin" in body
    assert isinstance(body["builtin"], list)


def test_boards_catalog(client) -> None:
    response = client.get("/v1/boards/catalog")
    assert response.status_code == 200
    body = response.json()
    assert body["board_count"] == len(body["boards"])
