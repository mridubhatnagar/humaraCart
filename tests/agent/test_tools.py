"""Tool execution tests: real guard, real DAOs, a controllable Instamart stub.

These cover what the model is *given back*, since that text is what it
re-reasons on. The graph-level concerns (looping, interrupts, injected
identity) are covered in test_graph.py.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.accounts.dao import AccountDAO
from app.accounts.models import Account
from app.agent.tools import build_tools
from app.cart.dao import ItemCartDAO
from app.cart.service import CartService
from app.groups.dao import GroupAccountDAO
from app.groups.models import Group, GroupAccount, Role
from app.instamart.client import IInstamartClient, InstamartDomainError
from app.instamart.types import (
    Cart,
    Order,
    OrderDetails,
    CartLineItem,
    CheckoutResult,
    PaymentOption,
    ProductVariation,
)

GROUP_ID = "g_priya_household"
ADDR = "addr_home"
PRIYA = "+919812345678"
RAHUL = "+919887654321"


class StubClient(IInstamartClient):
    """Controllable Instamart — each test sets exactly the condition it needs."""

    def __init__(
        self,
        variations=None,
        cart=None,
        checkout_result=None,
        raises=None,
        orders=None,
        order_details=None,
    ):
        self.orders = orders or []
        self.order_details = order_details
        self.variations = variations if variations is not None else []
        self.cart = cart or Cart(
            cart_id="c1", address_id=ADDR, items=[], total=0, to_pay=0
        )
        self.checkout_result = checkout_result
        self.raises = raises
        self.checkout_calls = []
        self.update_cart_calls = []

    def get_addresses(self):
        return []

    def search_products(self, address_id, query):
        if self.raises:
            raise self.raises
        return self.variations

    def update_cart(self, address_id, items):
        self.update_cart_calls.append((address_id, items))
        return self.cart

    def get_cart(self):
        return self.cart

    def clear_cart(self):
        return None

    def get_payment_options(self):
        return [
            PaymentOption(id="UPI", label="UPI"),
            PaymentOption(id="COD", label="Pay on delivery"),
        ]

    def checkout(self, address_id, payment_method=None):
        self.checkout_calls.append((address_id, payment_method))
        return self.checkout_result

    def get_orders(self):
        return self.orders

    def get_order_details(self, order_id):
        return self.order_details


@pytest.fixture
def account_dao(session):
    dao = AccountDAO(session, Fernet(Fernet.generate_key()))
    session.add(Group(group_id=GROUP_ID, address_id=ADDR))
    session.commit()
    dao.create(Account(phone=PRIYA, name="Priya"))
    dao.create(Account(phone=RAHUL, name="Rahul"))
    ga = GroupAccountDAO(session)
    ga.create(GroupAccount(group_id=GROUP_ID, account_id=PRIYA, role=Role.HOLDER))
    ga.create(GroupAccount(group_id=GROUP_ID, account_id=RAHUL, role=Role.MEMBER))
    return dao


@pytest.fixture
def state():
    return {
        "messages": [],
        "group_id": GROUP_ID,
        "address_id": ADDR,
        "requested_by": PRIYA,
        "pending_options": None,
        "pending_confirmation": None,
        "checkout_confirmed": False,
        "cart_changed": False,
        "last_change": None,
        "notify_holder": None,
        "announce": None,
        "direct_reply": None,
        "last_order_id": None,
    }


@pytest.fixture
def confirmed_state(state):
    """State after the user has approved the order at the interrupt."""
    return {**state, "checkout_confirmed": True}


def make_tools(session, account_dao, client, group_account_dao=None):
    if group_account_dao is None:
        group_account_dao = GroupAccountDAO(session)
    return build_tools(
        client,
        CartService(client, ItemCartDAO(session)),
        account_dao,
        group_account_dao,
    )


def make_tools_with_an_item(session, account_dao, client, state):
    """Checkout now refuses an empty list, so these tests need one item on it."""
    tools = make_tools(session, account_dao, client)
    tools["update_cart"]({"spin_id": "spin_milk", "quantity": 1}, state)
    return tools


def test_search_with_several_variants_returns_options(session, account_dao, state):
    client = StubClient(
        variations=[
            ProductVariation(spin_id="a", label="Amul Taaza 1L", price=66),
            ProductVariation(spin_id="b", label="Amul Gold 500ml", price=40),
        ]
    )
    result = make_tools(session, account_dao, client)["search_products"](
        {"query": "milk"}, state
    )

    assert result.options is not None
    assert [o["spin_id"] for o in result.options] == ["a", "b"]
    assert "Amul Taaza 1L" in result.content


def test_search_with_one_variant_returns_no_options(session, account_dao, state):
    client = StubClient(
        variations=[ProductVariation(spin_id="a", label="Amul Taaza 1L", price=66)]
    )
    result = make_tools(session, account_dao, client)["search_products"](
        {"query": "milk"}, state
    )

    assert result.options is None
    assert "spin_id=a" in result.content


def test_search_with_no_match(session, account_dao, state):
    result = make_tools(session, account_dao, StubClient())["search_products"](
        {"query": "unicorn"}, state
    )
    assert "Nothing matched" in result.content


def test_search_all_out_of_stock(session, account_dao, state):
    client = StubClient(
        variations=[
            ProductVariation(
                spin_id="a", label="Amul Butter", price=285, available=False
            )
        ]
    )
    result = make_tools(session, account_dao, client)["search_products"](
        {"query": "butter"}, state
    )

    assert result.options is None
    assert "out of stock" in result.content


def test_search_failure_is_returned_not_raised(session, account_dao, state):
    """The model must see the failure as a result so it can re-reason."""
    client = StubClient(raises=InstamartDomainError("ADDRESS_NOT_SERVICEABLE"))
    result = make_tools(session, account_dao, client)["search_products"](
        {"query": "milk"}, state
    )

    assert "ADDRESS_NOT_SERVICEABLE" in result.content


def test_update_cart_adds_item(session, account_dao, state):
    client = StubClient()
    tools = make_tools(session, account_dao, client)

    result = tools["update_cart"]({"spin_id": "spin_milk", "quantity": 1}, state)

    assert "Added" in result.content
    assert client.update_cart_calls  # the guard pushed to Instamart


def test_duplicate_names_the_original_requester(session, account_dao, state):
    """The money shot: phone resolved to a name, not echoed as a number."""
    tools = make_tools(session, account_dao, StubClient())
    tools["update_cart"]({"spin_id": "spin_milk", "quantity": 1}, state)

    rahul_state = {**state, "requested_by": RAHUL}
    result = tools["update_cart"]({"spin_id": "spin_milk", "quantity": 1}, rahul_state)

    assert "Already in the cart, added by Priya." == result.content
    assert PRIYA not in result.content


def test_quantity_zero_removes(session, account_dao, state):
    tools = make_tools(session, account_dao, StubClient())
    tools["update_cart"]({"spin_id": "spin_milk", "quantity": 1}, state)

    result = tools["update_cart"]({"spin_id": "spin_milk", "quantity": 0}, state)

    assert "Removed" in result.content


def test_removing_something_absent(session, account_dao, state):
    tools = make_tools(session, account_dao, StubClient())
    result = tools["update_cart"]({"spin_id": "spin_milk", "quantity": 0}, state)

    assert "not in the cart" in result.content


def test_get_cart_empty(session, account_dao, state):
    result = make_tools(session, account_dao, StubClient())["get_cart"]({}, state)
    assert "empty" in result.content


def test_get_cart_lists_items_with_attribution(session, account_dao, state):
    client = StubClient(
        cart=Cart(
            cart_id="c1",
            address_id=ADDR,
            items=[
                CartLineItem(
                    spin_id="spin_milk", name="Amul Taaza 1L", quantity=2, price=66
                )
            ],
            total=132,
            to_pay=132,
        )
    )
    tools = make_tools(session, account_dao, client)
    tools["update_cart"]({"spin_id": "spin_milk", "quantity": 2}, state)

    result = tools["get_cart"]({}, state)

    assert "Amul Taaza 1L" in result.content
    assert "added by Priya" in result.content


def test_checkout_blocked_over_the_cap(session, account_dao, state):
    client = StubClient(
        cart=Cart(cart_id="c1", address_id=ADDR, items=[], total=1200, to_pay=1200)
    )
    result = make_tools_with_an_item(session, account_dao, client, state)["checkout"](
        {}, state
    )

    assert "Swiggy app" in result.content
    assert client.checkout_calls == []  # nothing was placed


def test_checkout_refuses_an_empty_cart(session, account_dao, state):
    """Nothing on the list means there is nothing to order — no confirmation prompt."""
    client = StubClient(
        cart=Cart(cart_id="c1", address_id=ADDR, items=[], total=0, to_pay=0)
    )
    result = make_tools(session, account_dao, client)["checkout"]({}, state)

    assert client.checkout_calls == []
    assert result.confirm is None
    assert "nothing to order" in result.content


def test_member_cannot_place_an_order_and_holder_is_nudged(session, account_dao, state):
    """It is the holder's Instamart account and their money — a member asking
    is a nudge, not an instruction."""
    client = StubClient(
        cart=Cart(cart_id="c1", address_id=ADDR, items=[], total=340, to_pay=340)
    )
    member_state = {**state, "requested_by": RAHUL}
    result = make_tools_with_an_item(session, account_dao, client, member_state)[
        "checkout"
    ]({"payment_method": "UPI"}, member_state)

    assert client.checkout_calls == []
    assert result.confirm is None  # not even a confirmation prompt
    assert "Rahul thinks the cart is ready" in result.notify_holder


def test_member_cannot_even_see_payment_options(session, account_dao, state):
    """The model calls this one *first* when asked to check out, so gating only
    `checkout` would let a member walk right up to paying."""
    client = StubClient()
    member_state = {**state, "requested_by": RAHUL}

    result = make_tools(session, account_dao, client)["get_payment_options"](
        {}, member_state
    )

    assert "UPI" not in result.content
    assert "Rahul thinks the cart is ready" in result.notify_holder


def test_holder_can_see_payment_options(session, account_dao, state):
    result = make_tools(session, account_dao, StubClient())["get_payment_options"](
        {}, state
    )

    assert "payment_method=UPI" in result.content
    assert "payment_method=COD" in result.content
    assert "gpay" not in result.content  # deeplinks are not payment methods
    assert result.notify_holder is None


def test_holder_placing_an_order_announces_it_to_the_household(
    session, account_dao, confirmed_state
):
    client = StubClient(
        cart=Cart(cart_id="c1", address_id=ADDR, items=[], total=340, to_pay=340),
        checkout_result=CheckoutResult(
            bridge_url=None,
            upi_intent_url=None,
            paas_id="p1",
            order_id="o1",
            status="CONFIRMED",
        ),
    )
    result = make_tools_with_an_item(session, account_dao, client, confirmed_state)[
        "checkout"
    ]({"payment_method": "COD"}, confirmed_state)

    assert "o1" in result.announce


def test_a_pending_payment_link_is_never_announced(
    session, account_dao, confirmed_state
):
    """The order is not placed until payment clears, and the link is the
    holder's alone — it must never reach the household."""
    link = "https://bridge.swiggy.com/pay/secret-token"
    client = StubClient(
        cart=Cart(cart_id="c1", address_id=ADDR, items=[], total=340, to_pay=340),
        checkout_result=CheckoutResult(
            bridge_url=link,
            upi_intent_url="upi://x",
            paas_id="p1",
            order_id="o1",
            status="PENDING_PAYMENT",
        ),
    )
    result = make_tools_with_an_item(session, account_dao, client, confirmed_state)[
        "checkout"
    ]({"payment_method": "UPI"}, confirmed_state)

    assert result.announce is None
    assert link in result.direct_reply  # goes straight to the holder, verbatim
    assert link not in result.content  # never passes through the model


def test_checkout_refuses_until_confirmed(session, account_dao, state):
    """Code refuses to place the order, rather than asking the model to behave."""
    client = StubClient(
        cart=Cart(cart_id="c1", address_id=ADDR, items=[], total=340, to_pay=340)
    )
    result = make_tools_with_an_item(session, account_dao, client, state)["checkout"](
        {"payment_method": "UPI"}, state
    )

    assert client.checkout_calls == []
    assert result.confirm["to_pay"] == 340
    assert result.confirm["payment_method"] == "UPI"


def test_checkout_places_order_under_the_cap(session, account_dao, confirmed_state):
    client = StubClient(
        cart=Cart(cart_id="c1", address_id=ADDR, items=[], total=340, to_pay=340),
        checkout_result=CheckoutResult(
            bridge_url=None,
            upi_intent_url=None,
            paas_id="p1",
            order_id="o1",
            status="CONFIRMED",
        ),
    )
    result = make_tools_with_an_item(session, account_dao, client, confirmed_state)[
        "checkout"
    ]({"payment_method": "COD"}, confirmed_state)

    assert client.checkout_calls == [(ADDR, "COD")]
    assert "o1" in result.content


def test_checkout_returns_the_full_payment_link(session, account_dao, confirmed_state):
    """The bridgeUrl must reach the user whole — a truncated one fails as
    "link expired". It is sent verbatim rather than through the model, so
    there is nothing that could paraphrase or shorten it."""
    link = "https://bridge.swiggy.com/pay/very/long/token/abc123xyz"
    client = StubClient(
        cart=Cart(cart_id="c1", address_id=ADDR, items=[], total=340, to_pay=340),
        checkout_result=CheckoutResult(
            bridge_url=link,
            upi_intent_url="upi://x",
            paas_id="p1",
            order_id="o1",
            status="PENDING_PAYMENT",
        ),
    )
    result = make_tools_with_an_item(session, account_dao, client, confirmed_state)[
        "checkout"
    ]({"payment_method": "UPI"}, confirmed_state)

    assert link in result.direct_reply
    assert link not in result.content
