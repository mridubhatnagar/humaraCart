"""The real `IMessenger` — sends via Twilio's REST API using the official SDK
(already a dependency), rather than hand-rolling HTTP calls in product code.
"""

from __future__ import annotations

from twilio.rest import Client

from app.whatsapp.messenger import IMessenger


class TwilioMessenger(IMessenger):
    def __init__(self, account_sid: str, auth_token: str, whatsapp_from: str) -> None:
        self._client = Client(account_sid, auth_token)
        self._from = f"whatsapp:{whatsapp_from}"

    def send(self, to: str, text: str) -> None:
        self._client.messages.create(from_=self._from, to=f"whatsapp:{to}", body=text)
