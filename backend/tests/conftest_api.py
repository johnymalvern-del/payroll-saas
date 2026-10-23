
"""Shared FastAPI TestClient fixture for endpoint tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def api_client() -> TestClient:
    with TestClient(app) as client:
        yield client
