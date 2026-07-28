"""The single seam between HumaraCart and Instamart.

Everything above this interface (the guard, the agent) is written against
`IInstamartClient` and never against a concrete backend — `McpInstamartClient`
(real MCP) and `MockInstamartClient` (test double, no network/login) implement
it. The methods mirror Swiggy's actual MCP tool shapes directly (per
`IMPLEMENTATION_PLAN.md` §5/§7: the agent calls these tools directly, no
household-semantic wrapper), not an abstracted add/remove-per-item cart.

One `IInstamartClient` instance is scoped to a single Instamart session (one
bearer token = one account = one household in our model) — there is no
household_id parameter anywhere here, unlike the pre-MCP prototype.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.instamart.types import (
    Address,
    Cart,
    CartItemRequest,
    CheckoutResult,
    Order,
    OrderDetails,
    PaymentOption,
    ProductVariation,
)


class InstamartAuthError(Exception):
    """The session's bearer token is invalid or expired — re-run OAuth."""


class InstamartDomainError(Exception):
    """Swiggy answered but declined the request (e.g. min-order, not serviceable) —
    terminal, not retryable; the message is meant to be surfaced to the user."""


class InstamartUpstreamError(Exception):
    """Network/server trouble that persisted after retrying with backoff."""


class IInstamartClient(ABC):
    """Cart-and-catalog operations, mirroring the Instamart MCP tools directly."""

    @abstractmethod
    def get_addresses(self) -> list[Address]:
        """Saved delivery addresses. Swiggy mandates STOPping here and letting the
        user choose before any other tool call — never auto-pick."""

    @abstractmethod
    def search_products(self, address_id: str, query: str) -> list[ProductVariation]:
        """Resolve free text (e.g. "milk") to variations. Swiggy mandates asking
        the user which variation before adding to cart unless size/qty was given."""

    @abstractmethod
    def update_cart(self, address_id: str, items: list[CartItemRequest]) -> Cart:
        """Full-replace the cart with `items` — there is no incremental add/remove
        tool. Callers must send the complete desired item set every time."""

    @abstractmethod
    def get_cart(self) -> Cart:
        """Current cart state — display + stock/price reconciliation only, never
        used to decide what *should* be in the cart."""

    @abstractmethod
    def clear_cart(self) -> None: ...

    @abstractmethod
    def get_payment_options(self) -> list[PaymentOption]:
        """Methods `checkout` will accept — verified live as UPI and COD."""

    @abstractmethod
    def checkout(
        self, address_id: str, payment_method: str | None = None
    ) -> CheckoutResult:
        """Places a real order. Caller must have already confirmed with the user
        and checked the cart total is < ₹1000."""

    @abstractmethod
    def get_orders(self) -> list[OrderDetails]:
        """Newest first, with items, bill and status.

        Note `get_order_details` is deliberately absent: it is documented, but
        Swiggy gates it to beta accounts and refuses for ours. `get_orders`
        already returns the same fields.
        """
