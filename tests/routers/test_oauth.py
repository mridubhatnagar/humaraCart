"""OAuth callback router tests: verifies the route delegates correctly."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.dependencies import get_onboarding_service
from app.main import app


def test_oauth_callback_delegates_to_onboarding_service():
    fake_onboarding = MagicMock()
    app.dependency_overrides[get_onboarding_service] = lambda: fake_onboarding
    try:
        with TestClient(app) as client:
            response = client.get(
                "/oauth/callback", params={"code": "abc", "state": "xyz"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "Instamart linked" in response.text
    fake_onboarding.complete_holder_oauth.assert_called_once_with("abc", "xyz")
