"""The real `IMessenger` — sends via Twilio's REST API using the official SDK
(already a dependency), rather than hand-rolling HTTP calls in product code.
"""

from __future__ import annotations

from twilio.rest import Client

from app.whatsapp.messenger import IMessenger


class TwilioMessenger(IMessenger):
    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        whatsapp_from: str,
        status_callback_url: str | None = None,
    ) -> None:
        self._client = Client(account_sid, auth_token)
        self._from = f"whatsapp:{whatsapp_from}"
        self._status_callback_url = status_callback_url

    def send(self, to: str, text: str) -> None:
        kwargs = {}
        if self._status_callback_url:
            kwargs["status_callback"] = self._status_callback_url
        self._client.messages.create(
            from_=self._from, to=f"whatsapp:{to}", body=text, **kwargs
        )
