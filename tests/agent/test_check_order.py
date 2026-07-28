"""`check_order` — the closing beat.

After the payment link is sent the conversation otherwise just stops. This is
what answers "did it go through?", from Swiggy rather than from memory, and
puts the confirmation on every phone in the household.
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
from app.instamart.client import IInstamartClient, InstamartUpstreamError
from app.instamart.types import Cart, Order, OrderDetails

GROUP_ID = "g_priya_household"
ADDR = "addr_home"
PRIYA = "+919812345678"
RAHUL = "+919887654321"


class OrderStub(IInstamartClient):
    def __init__(self, orders=None, details=None, raises=None):
        self._orders = orders or []
        self._details = details
        self._raises = raises
        self.asked_for = []

    def get_orders(self):
        if self._raises:
            raise self._raises
        return self._orders

    def get_addresses(self):
        return []

    def search_products(self, address_id, query):
        return []

    def update_cart(self, address_id, items):
        return Cart(cart_id="c", address_id=ADDR)

    def get_cart(self):
        return Cart(cart_id="c", address_id=ADDR)

    def clear_cart(self):
        return None

    def get_payment_options(self):
        return []

    def checkout(self, address_id, payment_method=None):
        return None


@pytest.fixture
def tools_for(session):
    session.add(Group(group_id=GROUP_ID, address_id=ADDR))
    session.commit()
    account_dao = AccountDAO(session, Fernet(Fernet.generate_key()))
    account_dao.create(Account(phone=PRIYA, name="Priya"))
    group_account_dao = GroupAccountDAO(session)
    group_account_dao.create(
        GroupAccount(group_id=GROUP_ID, account_id=PRIYA, role=Role.HOLDER)
    )

    def make(client):
        return build_tools(
            client,
            CartService(client, ItemCartDAO(session)),
            account_dao,
            group_account_dao,
        )

    return make


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


def test_a_confirmed_order_is_announced_to_the_household(tools_for, state):
    client = OrderStub(
        orders=[
            OrderDetails(
                order_id="o1",
                status="Order Confirmed!",
                payment_status="PENDING",
                items=["Amul Masti Dahi 380 g x1"],
                total=170.0,
            )
        ]
    )
    result = tools_for(client)["check_order"]({}, state)

    assert "Order placed" in result.announce
    assert "Amul Masti Dahi" in result.announce
    assert "₹170.0" in result.announce


@pytest.mark.parametrize(
    "status,payment_status,expect_announce",
    [
        pytest.param(
            "Order Confirmed!",
            "PENDING",
            True,
            id="pending-payment-still-announces",
        ),
        pytest.param(
            "Order cancelled",
            "FAILED",
            False,
            id="cancelled-order-is-not-announced",
        ),
    ],
)
def test_announcement_gate_depends_on_status_not_payment(
    tools_for, state, status, payment_status, expect_announce
):
    """Swiggy leaves paymentStatus PENDING well after confirming a UPI order —
    waiting for SUCCESS would stay silent exactly when it matters."""
    client = OrderStub(
        orders=[
            OrderDetails(order_id="o1", status=status, payment_status=payment_status)
        ]
    )
    result = tools_for(client)["check_order"]({}, state)

    assert (result.announce is not None) == expect_announce


def test_the_most_recent_order_is_the_one_reported(tools_for, state):
    client = OrderStub(
        orders=[
            OrderDetails(
                order_id="newest",
                status="Order Confirmed!",
                payment_status="PENDING",
                items=["New thing x1"],
            ),
            OrderDetails(
                order_id="older", status="Delivered", payment_status="SUCCESS"
            ),
        ]
    )
    result = tools_for(client)["check_order"]({}, state)

    assert "New thing" in result.direct_reply


def test_a_vanished_order_is_not_reported_as_an_older_one(tools_for, state):
    """An unpaid UPI order disappears from Swiggy's list. Falling back to "most
    recent" would announce a week-old delivery as though it just happened."""
    client = OrderStub(
        orders=[
            OrderDetails(
                order_id="old_delivered",
                status="Order delivered on 27 Jul",
                payment_status="SUCCESS",
                items=["Potato chips x1"],
                total=125.0,
            )
        ]
    )
    placed_state = {**state, "last_order_id": "the_one_we_placed"}

    result = tools_for(client)["check_order"]({}, placed_state)

    assert result.announce is None
    assert "nothing was charged" in result.direct_reply
    assert "chips" not in result.direct_reply.lower()


def test_the_order_we_placed_is_found_among_others(tools_for, state):
    client = OrderStub(
        orders=[
            OrderDetails(
                order_id="newest_unrelated",
                status="Delivered",
                payment_status="SUCCESS",
            ),
            OrderDetails(
                order_id="ours",
                status="Order Confirmed!",
                payment_status="PENDING",
                items=["Amul Dahi x1"],
                total=170.0,
            ),
        ]
    )
    placed_state = {**state, "last_order_id": "ours"}

    result = tools_for(client)["check_order"]({}, placed_state)

    assert "Amul Dahi" in result.announce


def test_no_orders_at_all(tools_for, state):
    result = tools_for(OrderStub())["check_order"]({}, state)

    assert "No orders found" in result.content
    assert result.announce is None


def test_instamart_failure_is_reported_not_raised(tools_for, state):
    client = OrderStub(raises=InstamartUpstreamError("timeout"))
    result = tools_for(client)["check_order"]({}, state)

    assert "Could not check the order" in result.content
    assert result.announce is None
