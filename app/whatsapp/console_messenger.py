"""Prints instead of sending — local dev with zero Twilio credit spend, and the
test double for anything that depends on `IMessenger`. `sent` is inspectable
directly in tests, same pattern as `MockInstamartClient`.
"""

from __future__ import annotations

from app.whatsapp.messenger import IMessenger


class ConsoleMessenger(IMessenger):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, to: str, text: str) -> None:
        self.sent.append((to, text))
        print(f"[WhatsApp -> {to}] {text}")
