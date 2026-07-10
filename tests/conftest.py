"""Pytest fixtures for the API test suite."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def _env() -> None:
    os.environ.setdefault("MPYHW_ENV", "test")


@pytest.fixture()
def client() -> TestClient:
    from app.main import app

    return TestClient(app)
