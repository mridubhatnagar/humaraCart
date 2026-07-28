"""In-memory Instamart stand-in — the offline unit-test double for `IInstamartClient`.

`McpInstamartClient` is the real backend the demo runs against; this class
implements the same interface for tests only. One instance = one session (no
household_id parameter, matching the real interface — a bearer token scopes
to a single account). A fixed dummy catalog and an in-memory cart keep it
deterministic: every keyword resolves to exactly one product, so tests behave
identically on every run.
"""

from __future__ import annotations

from app.instamart.client import IInstamartClient
from app.instamart.types import (
    PaymentOption,
    Address,
    Cart,
    CartItemRequest,
    CartLineItem,
    CheckoutResult,
    Order,
    OrderDetails,
    ProductVariation,
)

# Keyword -> product variation. Brands are pre-resolved (V1 does not disambiguate).
# One obvious synonym each so natural phrasing still resolves in tests.
_CATALOG: dict[str, ProductVariation] = {
    "milk": ProductVariation(spin_id="spin_milk", label="Amul Taaza Milk 1L", price=66),
    "detergent": ProductVariation(
        spin_id="spin_detergent", label="Surf Excel Matic 1kg", price=210
    ),
    "chips": ProductVariation(
        spin_id="spin_chips", label="Lay's Classic Salted 52g", price=20
    ),
    "bread": ProductVariation(
        spin_id="spin_bread", label="Britannia Brown Bread 400g", price=45
    ),
    "eggs": ProductVariation(
        spin_id="spin_eggs", label="Fresho Eggs (6 pcs)", price=72
    ),
    "coffee": ProductVariation(
        spin_id="spin_coffee", label="Nescafe Classic 50g", price=175
    ),
    "sugar": ProductVariation(spin_id="spin_sugar", label="Madhur Sugar 1kg", price=55),
    "onions": ProductVariation(
        spin_id="spin_onions", label="Fresho Onion 1kg", price=40
    ),
    # An intentionally out-of-stock item, so the "unavailable" path is testable.
    "butter": ProductVariation(
        spin_id="spin_butter", label="Amul Butter 500g", price=285, available=False
    ),
}
_BY_SPIN_ID = {p.spin_id: p for p in _CATALOG.values()}

_SYNONYMS: dict[str, str] = {
    "doodh": "milk",
    "surf": "detergent",
    "wafers": "chips",
    "bread loaf": "bread",
    "egg": "eggs",
    "pyaz": "onions",
}

_ADDRESS = Address(id="addr_home", tag="Home", line="221B Baker Street")


class MockInstamartClient(IInstamartClient):
    def __init__(self) -> None:
        self._cart: dict[str, int] = {}  # spin_id -> quantity
        self._orders: list[OrderDetails] = []

    def get_addresses(self) -> list[Address]:
        return [_ADDRESS]

    def search_products(self, address_id: str, query: str) -> list[ProductVariation]:
        key = query.strip().lower()
        key = _SYNONYMS.get(key, key)
        product = _CATALOG.get(key)
        return [product] if product else []

    def update_cart(self, address_id: str, items: list[CartItemRequest]) -> Cart:
        self._cart = {i.spin_id: i.quantity for i in items}
        return self.get_cart()

    def get_cart(self) -> Cart:
        line_items = []
        total = 0.0
        for spin_id, qty in self._cart.items():
            product = _BY_SPIN_ID.get(spin_id)
            if product is None:
                continue
            line_items.append(
                CartLineItem(
                    spin_id=spin_id,
                    name=product.label,
                    quantity=qty,
                    price=product.price,
                )
            )
            total += (product.price or 0) * qty
        return Cart(
            cart_id="mock_cart",
            address_id=_ADDRESS.id,
            items=line_items,
            total=total,
            to_pay=total,
        )

    def clear_cart(self) -> None:
        self._cart = {}

    def get_payment_options(self) -> list[PaymentOption]:
        return [
            PaymentOption(id="UPI", label="UPI"),
            PaymentOption(id="COD", label="Pay on delivery"),
        ]

    def checkout(
        self, address_id: str, payment_method: str | None = None
    ) -> CheckoutResult:
        order_id = f"mock_order_{len(self._orders) + 1}"
        self._orders.append(
            OrderDetails(
                order_id=order_id,
                status="Order placed",
                payment_status="SUCCESS",
                items=["Amul Taaza Milk 1L x1"],
                total=66.0,
            )
        )
        self._cart = {}
        return CheckoutResult(
            bridge_url=None,
            upi_intent_url=None,
            paas_id="mock_paas",
            order_id=order_id,
            status="CONFIRMED",
        )

    def get_orders(self) -> list[OrderDetails]:
        return list(reversed(self._orders))
