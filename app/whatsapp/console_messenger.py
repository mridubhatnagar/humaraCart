"""Prints instead of sending — local dev with zero Twilio credit spend, and the
test double for anything that depends on `IMessenger`. `sent` is inspectable
directly in tests, same pattern as `MockInstamartClient`.
"""

from __future__ import annotations

import logging

from app.whatsapp.messenger import IMessenger

logger = logging.getLogger(__name__)


class ConsoleMessenger(IMessenger):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, to: str, text: str) -> None:
        self.sent.append((to, text))
        logger.info("[WhatsApp -> %s] %s", to, text)
