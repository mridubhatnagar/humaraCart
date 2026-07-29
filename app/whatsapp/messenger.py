"""`IMessenger` — the seam between HumaraCart and WhatsApp.

`ConsoleMessenger` (dev/test, no network) and `TwilioMessenger` (real) both
implement this. `broadcast` is a pure loop over `send`, so it's concrete on
the interface (same Template Method pattern as `IAccountDAO.get_by_phone`) —
every implementation gets it for free.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class IMessenger(ABC):
    @abstractmethod
    def send(self, to: str, text: str) -> None: ...

    def broadcast(self, recipients: list[str], text: str) -> None:
        for r in recipients:
            self.send(r, text)
