"""MockInstamartClient tests: the offline test double behaves like the real interface."""

from __future__ import annotations

from app.instamart.mock import MockInstamartClient
from app.instamart.types import CartItemRequest

ADDR = "addr_home"


def test_get_addresses_returns_one_fixed_address():
    client = MockInstamartClient()
    addresses = client.get_addresses()
    assert len(addresses) == 1
    assert addresses[0].id == ADDR


def test_search_resolves_known_item():
    client = MockInstamartClient()
    results = client.search_products(ADDR, "milk")
    assert len(results) == 1
    assert results[0].label == "Amul Taaza Milk 1L"


def test_search_synonym_resolves():
    client = MockInstamartClient()
    results = client.search_products(ADDR, "doodh")
    assert results[0].spin_id == "spin_milk"


def test_search_unknown_item_returns_empty():
    client = MockInstamartClient()
    assert client.search_products(ADDR, "unicorn") == []


def test_search_out_of_stock_item_flagged_unavailable():
    client = MockInstamartClient()
    results = client.search_products(ADDR, "butter")
    assert results[0].available is False


def test_update_cart_is_full_replace_not_incremental():
    client = MockInstamartClient()
    client.update_cart(ADDR, [CartItemRequest(spin_id="spin_milk", quantity=1)])
    client.update_cart(ADDR, [CartItemRequest(spin_id="spin_chips", quantity=2)])
    cart = client.get_cart()
    spin_ids = {i.spin_id for i in cart.items}
    assert spin_ids == {"spin_chips"}  # milk is gone — full replace, not additive


def test_get_cart_reflects_total():
    client = MockInstamartClient()
    client.update_cart(ADDR, [CartItemRequest(spin_id="spin_milk", quantity=2)])
    cart = client.get_cart()
    assert cart.total == 66 * 2
    assert cart.to_pay == 66 * 2


def test_clear_cart_empties_it():
    client = MockInstamartClient()
    client.update_cart(ADDR, [CartItemRequest(spin_id="spin_milk", quantity=1)])
    client.clear_cart()
    assert client.get_cart().items == []


def test_checkout_returns_confirmed_and_empties_cart():
    client = MockInstamartClient()
    client.update_cart(ADDR, [CartItemRequest(spin_id="spin_milk", quantity=1)])
    result = client.checkout(ADDR, payment_method="UPI")
    assert result.status == "CONFIRMED"
    assert result.order_id is not None
    assert client.get_cart().items == []


def test_get_orders_accumulates_after_checkout():
    client = MockInstamartClient()
    client.update_cart(ADDR, [CartItemRequest(spin_id="spin_milk", quantity=1)])
    client.checkout(ADDR)
    orders = client.get_orders()
    assert len(orders) == 1
