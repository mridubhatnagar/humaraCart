"""Webhook router tests: signature verification bypassed via dependency override;
onboarding dispatch verified via a captured call. TestClient runs the background
task synchronously before returning, so it's assertable right after the request.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.dependencies import get_conversation_service, get_verified_twilio_form
from app.main import app


def test_webhook_dispatches_to_conversation_service():
    fake_conversation = MagicMock()
    app.dependency_overrides[get_verified_twilio_form] = lambda: {
        "From": "whatsapp:+919812345678",
        "Body": "hi",
    }
    app.dependency_overrides[get_conversation_service] = lambda: fake_conversation
    try:
        with TestClient(app) as client:
            response = client.post(
                "/webhook", data={"From": "whatsapp:+919812345678", "Body": "hi"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert response.text == "<Response></Response>"
    fake_conversation.handle.assert_called_once_with("+919812345678", "hi", None)


def test_real_form_parsing_and_signature_check_run():
    """Exercises get_verified_twilio_form for real — no override.

    A bad signature must give 403. Anything else (500, AssertionError) means
    the form body never parsed, which is how a missing python-multipart slips
    through: the other test overrides this dependency, so it never runs.
    """
    fake_conversation = MagicMock()
    app.dependency_overrides[get_conversation_service] = lambda: fake_conversation
    try:
        with TestClient(app) as client:
            response = client.post(
                "/webhook",
                data={"From": "whatsapp:+919812345678", "Body": "hi"},
                headers={"X-Twilio-Signature": "obviously-not-valid"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    fake_conversation.handle.assert_not_called()
