"""In-memory Instamart stand-in for the demo.

A fixed dummy catalog and in-memory per-household carts. Deterministic on
purpose: every keyword resolves to exactly one product, so a recorded demo
behaves identically on every take. Swap this for `McpInstamartClient` when
production credentials arrive; the interface stays identical.
"""

from __future__ import annotations

from app.instamart.client import InstamartClient
from app.models import CartEntry, Product

# Keyword -> product. Brands are pre-resolved (V1 does not disambiguate).
# One obvious synonym each so natural phrasing still resolves on camera.
_CATALOG: dict[str, Product] = {
    "milk": Product("p_milk", "Amul Taaza Milk 1L", "Amul", 66),
    "detergent": Product("p_detergent", "Surf Excel Matic 1kg", "Surf Excel", 210),
    "chips": Product("p_chips", "Lay's Classic Salted 52g", "Lay's", 20),
    "bread": Product("p_bread", "Britannia Brown Bread 400g", "Britannia", 45),
    "eggs": Product("p_eggs", "Fresho Eggs (6 pcs)", "Fresho", 72),
    "coffee": Product("p_coffee", "Nescafe Classic 50g", "Nescafe", 175),
    "sugar": Product("p_sugar", "Madhur Sugar 1kg", "Madhur", 55),
    "onions": Product("p_onions", "Fresho Onion 1kg", "Fresho", 40),
    # An intentionally out-of-stock item, so the "unavailable" path is demoable.
    "butter": Product("p_butter", "Amul Butter 500g", "Amul", 285, available=False),
}

_SYNONYMS: dict[str, str] = {
    "doodh": "milk",
    "surf": "detergent",
    "wafers": "chips",
    "bread loaf": "bread",
    "egg": "eggs",
    "pyaz": "onions",
}


class MockInstamartClient(InstamartClient):
    def __init__(self) -> None:
        # household_id -> {product_id: CartEntry}
        self._carts: dict[str, dict[str, CartEntry]] = {}

    def search_products(self, query: str) -> list[Product]:
        key = query.strip().lower()
        key = _SYNONYMS.get(key, key)
        product = _CATALOG.get(key)
        return [product] if product else []

    def update_cart(
        self, household_id: str, product: Product, qty: int, action: str
    ) -> None:
        cart = self._carts.setdefault(household_id, {})
        if action == "add":
            if product.id in cart:
                cart[product.id] = CartEntry(product, cart[product.id].qty + qty)
            else:
                cart[product.id] = CartEntry(product, qty)
        elif action == "remove":
            cart.pop(product.id, None)
        else:
            raise ValueError(f"unknown cart action: {action!r}")

    def get_cart(self, household_id: str) -> list[CartEntry]:
        return list(self._carts.get(household_id, {}).values())
