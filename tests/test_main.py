"""Confirms the FastAPI app actually boots and responds — M1's own verification bar."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_health_check():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
