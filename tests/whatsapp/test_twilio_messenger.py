"""TwilioMessenger tests: verifies the Twilio SDK is called correctly. No real network."""

from __future__ import annotations

from unittest.mock import patch

from app.whatsapp.twilio_messenger import TwilioMessenger


def test_send_calls_twilio_messages_create():
    with patch("app.whatsapp.twilio_messenger.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        messenger = TwilioMessenger("SID", "TOKEN", "+10000000000")
        messenger.send("+919812345678", "hello")

    mock_client_cls.assert_called_once_with("SID", "TOKEN")
    mock_client.messages.create.assert_called_once_with(
        from_="whatsapp:+10000000000", to="whatsapp:+919812345678", body="hello"
    )


def test_broadcast_sends_to_every_recipient():
    with patch("app.whatsapp.twilio_messenger.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        messenger = TwilioMessenger("SID", "TOKEN", "+10000000000")
        messenger.broadcast(["+91111", "+91222"], "update")

    assert mock_client.messages.create.call_count == 2


def test_send_includes_status_callback_when_configured():
    with patch("app.whatsapp.twilio_messenger.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        messenger = TwilioMessenger(
            "SID",
            "TOKEN",
            "+10000000000",
            status_callback_url="https://humaracart.mridulabs.dev/webhook/status",
        )
        messenger.send("+919812345678", "hello")

    mock_client.messages.create.assert_called_once_with(
        from_="whatsapp:+10000000000",
        to="whatsapp:+919812345678",
        body="hello",
        status_callback="https://humaracart.mridulabs.dev/webhook/status",
    )
