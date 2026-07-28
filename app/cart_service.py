"""The core household-cart engine.

This is the part that must be rock-solid for the demo. It has no dependency on
WhatsApp, Twilio, or any LLM — it takes plain arguments and returns plain
results, which makes it fully unit-testable (see tests/test_cart_service.py).

It orchestrates the Instamart tools the way the sequence diagram describes:
search_products -> (dedup check) -> update_cart -> get_cart, and it owns the
household-layer `added_by` metadata that Instamart itself does not track.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.instamart.client import InstamartClient
from app.models import CartLine, Product


class AddStatus(str, Enum):
    ADDED = "added"
    DUPLICATE = "duplicate"  # already on the shared list — the money shot
    NOT_FOUND = "not_found"  # nothing in the catalog matched
    UNAVAILABLE = "unavailable"  # matched, but out of stock


class RemoveStatus(str, Enum):
    REMOVED = "removed"
    NOT_IN_CART = "not_in_cart"
    NOT_FOUND = "not_found"


@dataclass
class AddResult:
    status: AddStatus
    product: Product | None = None
    # For DUPLICATE: who originally added the item.
    existing_added_by: str | None = None


@dataclass
class RemoveResult:
    status: RemoveStatus
    product: Product | None = None


class CartService:
    def __init__(self, client: InstamartClient) -> None:
        self._client = client
        # household_id -> {product_id: member_name who added it}
        self._added_by: dict[str, dict[str, str]] = {}

    # -- commands -----------------------------------------------------------

    def add(
        self, household_id: str, item: str, qty: int, member_name: str
    ) -> AddResult:
        matches = self._client.search_products(item)
        if not matches:
            return AddResult(AddStatus.NOT_FOUND)

        product = matches[0]  # auto-resolve; V1 does not disambiguate brands
        if not product.available:
            return AddResult(AddStatus.UNAVAILABLE, product=product)

        # Duplicate detection is against the live cart, not local state, so it
        # stays correct even if the cart was changed by another path.
        in_cart = {e.product.id for e in self._client.get_cart(household_id)}
        if product.id in in_cart:
            original = self._added_by.get(household_id, {}).get(product.id)
            return AddResult(
                AddStatus.DUPLICATE, product=product, existing_added_by=original
            )

        self._client.update_cart(household_id, product, qty, "add")
        self._added_by.setdefault(household_id, {})[product.id] = member_name
        return AddResult(AddStatus.ADDED, product=product)

    def remove(self, household_id: str, item: str, member_name: str) -> RemoveResult:
        matches = self._client.search_products(item)
        if not matches:
            return RemoveResult(RemoveStatus.NOT_FOUND)

        product = matches[0]
        in_cart = {e.product.id for e in self._client.get_cart(household_id)}
        if product.id not in in_cart:
            return RemoveResult(RemoveStatus.NOT_IN_CART, product=product)

        self._client.update_cart(household_id, product, 0, "remove")
        self._added_by.get(household_id, {}).pop(product.id, None)
        return RemoveResult(RemoveStatus.REMOVED, product=product)

    # -- queries ------------------------------------------------------------

    def items(self, household_id: str) -> list[CartLine]:
        """Compose Instamart's cart entries with household `added_by` metadata."""
        added_by = self._added_by.get(household_id, {})
        return [
            CartLine(
                product=entry.product,
                qty=entry.qty,
                added_by=added_by.get(entry.product.id, "someone"),
            )
            for entry in self._client.get_cart(household_id)
        ]

    def total(self, household_id: str) -> int:
        return sum(line.product.price * line.qty for line in self.items(household_id))
