"""Instamart-shaped value objects — the `IInstamartClient` interface's own types.

These mirror what the real Swiggy Instamart MCP returns; nothing here is
persisted (contrast with `app/cart/models.py`'s `ItemCart`, which is the local
source of truth cart writes are rebuilt from). Field names/shapes are grounded
in `scripts/verify_swiggy.py`'s proven live responses and `IMPLEMENTATION_PLAN.md`
§5 — exact inner field names are not officially published, so `McpInstamartClient`
parses defensively; these dataclasses are the typed result of that parsing.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Address:
    """A saved Instamart delivery address (from `get_addresses`)."""

    id: str
    tag: str
    line: str


@dataclass(frozen=True)
class ProductVariation:
    """One resolvable variation of a searched item (from `search_products`)."""

    spin_id: str
    label: str
    price: float | None
    available: bool = True


@dataclass(frozen=True)
class CartItemRequest:
    """One line of the full-replace payload sent to `update_cart`."""

    spin_id: str
    quantity: int


@dataclass(frozen=True)
class CartLineItem:
    """One line of the cart as Swiggy currently sees it (from `get_cart`/`update_cart`)."""

    spin_id: str
    name: str
    quantity: int
    price: float | None


@dataclass(frozen=True)
class Cart:
    """The live Instamart cart state — display + reconciliation only, never the
    source of truth for what *should* be in the cart (that's `ItemCart`, local)."""

    cart_id: str | None
    address_id: str | None
    items: list[CartLineItem] = field(default_factory=list)
    total: float | None = None
    to_pay: float | None = None
    # Swiggy's own bill lines as (label, display value) — "Item Total", fees,
    # delivery. Shown verbatim before checkout rather than recomputed.
    bill_lines: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class CheckoutResult:
    """The result of placing an order — `bridge_url` is what gets relayed over
    WhatsApp for UPI; never truncate it."""

    bridge_url: str | None
    upi_intent_url: str | None
    paas_id: str | None
    order_id: str | None
    status: str | None


@dataclass(frozen=True)
class PaymentOption:
    """A payment method `checkout` will actually accept.

    Deliberately *not* the per-app entries Swiggy lists inside the UPI group
    (`gpay://upi/`, `phonepe://`): those are deeplink ids, not payment methods,
    and passing one to `checkout` yields no payment link. The user picks their
    UPI app on the payment page itself.
    """

    id: str
    label: str


@dataclass(frozen=True)
class Order:
    order_id: str


@dataclass(frozen=True)
class OrderDetails:
    """One order as Swiggy reports it — the answer to "did it go through?"."""

    order_id: str
    status: str
    payment_status: str
    items: list[str] = field(default_factory=list)
    total: float | None = None
