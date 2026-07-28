"""Core domain types.

These are HumaraCart's own types, deliberately independent of any Instamart
payload shape. When the real Swiggy Instamart MCP is wired in later, only the
InstamartClient implementation maps MCP responses into these — nothing else in
the codebase changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class Product:
    """A resolvable item in the (mock) Instamart catalog."""

    id: str
    name: str
    brand: str
    price: int  # rupees, whole number is fine for the demo
    available: bool = True


@dataclass(frozen=True)
class CartEntry:
    """Instamart's view of a cart line: just a product and a quantity.

    This is what `InstamartClient.get_cart` returns. It carries no notion of
    which flatmate added the item, because the real Instamart cart has none.
    """

    product: Product
    qty: int


@dataclass
class CartLine:
    """HumaraCart's view of a cart line: a CartEntry plus who put it there.

    `added_by` is household-layer metadata owned by CartService, not Instamart.
    It powers the duplicate-catch message:
    "milk is already on the list (added by Priya)".
    """

    product: Product
    qty: int
    added_by: str


@dataclass
class Member:
    """A household member reachable on WhatsApp."""

    name: str
    phone: str  # E.164, e.g. "+919812345678"
    is_account_holder: bool = False


@dataclass
class Household:
    """A group of members sharing one Instamart cart."""

    id: str
    members: list[Member] = field(default_factory=list)

    @property
    def account_holder(self) -> Member:
        return next(m for m in self.members if m.is_account_holder)

    def member_by_phone(self, phone: str) -> Member | None:
        return next((m for m in self.members if m.phone == phone), None)


class Action(str, Enum):
    """What a member's message is asking HumaraCart to do."""

    ADD = "add"
    REMOVE = "remove"
    SHOW = "show"
    READY = "ready"  # nudge the account holder that the cart is ready
    SEND_LINK = "send_link"  # account holder asks for the checkout summary/link
    UNKNOWN = "unknown"


@dataclass
class Intent:
    """Structured result of classifying an inbound message."""

    action: Action
    item: str | None = None
    qty: int = 1


@dataclass
class OutgoingMessage:
    """One WhatsApp reply to send, addressed to a specific member."""

    to: Member
    text: str
