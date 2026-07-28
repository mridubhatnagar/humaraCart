"""The single seam between HumaraCart and Instamart.

Everything above this interface (cart logic, intent handling, WhatsApp) is
written against `InstamartClient` and never against a concrete backend. For the
demo the backend is `MockInstamartClient` (dummy catalog, in-memory carts).
When production credentials arrive, a `McpInstamartClient` implements the same
three methods by calling the real Swiggy Instamart MCP tools — and nothing that
consumes this interface has to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import CartEntry, Product


class InstamartClient(ABC):
    """Cart-and-catalog operations, mirroring the Instamart MCP tools."""

    @abstractmethod
    def search_products(self, query: str) -> list[Product]:
        """Resolve a free-text item (e.g. "milk") to catalog products.

        Returns an empty list when nothing matches. The caller auto-resolves to
        the first result (brands are not disambiguated in V1).
        """

    @abstractmethod
    def update_cart(
        self, household_id: str, product: Product, qty: int, action: str
    ) -> None:
        """Apply a change to the household cart. `action` is "add" or "remove"."""

    @abstractmethod
    def get_cart(self, household_id: str) -> list[CartEntry]:
        """Return the current cart entries (product + qty) for a household."""
