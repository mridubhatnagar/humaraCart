"""CartService (the guard) tests: full-replace-from-local, attribution, dedup.

These are the demo's foundation — must stay green.
"""

from __future__ import annotations

import pytest

from app.accounts.models import Account
from app.cart.dao import ItemCartDAO
from app.cart.service import AddStatus, CartService, RemoveStatus
from app.groups.models import Group
from app.instamart.client import InstamartDomainError
from app.instamart.mock import MockInstamartClient

GROUP_ID = "g_priya_household"
OTHER_GROUP_ID = "g_other_household"
ADDR = "addr_home"
PRIYA = "+919812345678"
RAHUL = "+919887654321"


@pytest.fixture
def client():
    return MockInstamartClient()


@pytest.fixture
def svc(session, client):
    session.add(Group(group_id=GROUP_ID, address_id=ADDR))
    session.add(Group(group_id=OTHER_GROUP_ID, address_id=ADDR))
    session.add(Account(phone=PRIYA, name="Priya"))
    session.add(Account(phone=RAHUL, name="Rahul"))
    session.commit()
    return CartService(client, ItemCartDAO(session))


def test_add_new_item(svc):
    res = svc.add(GROUP_ID, ADDR, "spin_milk", 1, PRIYA)
    assert res.status == AddStatus.ADDED
    assert [l.spin_id for l in svc.items(GROUP_ID)] == ["spin_milk"]


def test_add_duplicate_is_caught_and_attributed(svc):
    svc.add(GROUP_ID, ADDR, "spin_milk", 1, PRIYA)
    res = svc.add(GROUP_ID, ADDR, "spin_milk", 1, RAHUL)
    assert res.status == AddStatus.DUPLICATE
    assert res.existing_requested_by == PRIYA
    # Still exactly one milk in the cart — the duplicate add didn't insert a second row.
    assert [l.spin_id for l in svc.items(GROUP_ID)] == ["spin_milk"]


def test_remove_existing_item(svc):
    svc.add(GROUP_ID, ADDR, "spin_milk", 1, PRIYA)
    res = svc.remove(GROUP_ID, ADDR, "spin_milk")
    assert res.status == RemoveStatus.REMOVED
    assert svc.items(GROUP_ID) == []


def test_remove_absent_item(svc):
    assert svc.remove(GROUP_ID, ADDR, "spin_milk").status == RemoveStatus.NOT_IN_CART


def test_attribution_tracked_per_item(svc):
    svc.add(GROUP_ID, ADDR, "spin_milk", 1, PRIYA)
    svc.add(GROUP_ID, ADDR, "spin_chips", 1, RAHUL)
    by = {l.spin_id: l.requested_by for l in svc.items(GROUP_ID)}
    assert by == {"spin_milk": PRIYA, "spin_chips": RAHUL}


def test_households_are_isolated(svc):
    svc.add(GROUP_ID, ADDR, "spin_milk", 1, PRIYA)
    assert svc.items(OTHER_GROUP_ID) == []


def test_items_reconciled_with_live_name_and_price(svc):
    svc.add(GROUP_ID, ADDR, "spin_milk", 2, PRIYA)
    lines = svc.items(GROUP_ID)
    assert lines[0].name == "Amul Taaza Milk 1L"
    assert lines[0].price == 66
    assert lines[0].quantity == 2


def test_total_comes_from_instamart_not_our_arithmetic(svc, client):
    """Fees (handling, delivery, GST) are Swiggy's to state — we report their
    payable figure rather than summing item prices ourselves."""
    svc.add(GROUP_ID, ADDR, "spin_milk", 2, PRIYA)
    svc.add(GROUP_ID, ADDR, "spin_chips", 1, RAHUL)

    assert svc.total(GROUP_ID) == client.get_cart().to_pay


def test_add_sends_full_replace_not_a_delta(svc, client):
    """Every update_cart call must carry the WHOLE local set, not just the new item."""
    svc.add(GROUP_ID, ADDR, "spin_milk", 1, PRIYA)
    svc.add(GROUP_ID, ADDR, "spin_chips", 1, RAHUL)
    live_spin_ids = {i.spin_id for i in client.get_cart().items}
    assert live_spin_ids == {"spin_milk", "spin_chips"}


def test_remove_last_item_clears_the_remote_cart(svc, client):
    svc.add(GROUP_ID, ADDR, "spin_milk", 1, PRIYA)
    svc.remove(GROUP_ID, ADDR, "spin_milk")
    assert client.get_cart().items == []


class _RejectingClient(MockInstamartClient):
    """Instamart refuses the write, as it does for an invalid spin_id."""

    def update_cart(self, address_id, items):
        raise InstamartDomainError("invalid spinId")

    def clear_cart(self):
        raise InstamartDomainError("nope")


def test_failed_remote_add_leaves_no_local_row(session):
    """A row Swiggy rejected must not survive — local drives every later
    full-replace, so it would be re-sent forever and keep failing."""
    session.add(Group(group_id=GROUP_ID, address_id=ADDR))
    session.add(Account(phone=PRIYA, name="Priya"))
    session.commit()
    dao = ItemCartDAO(session)
    svc = CartService(_RejectingClient(), dao)

    with pytest.raises(InstamartDomainError):
        svc.add(GROUP_ID, ADDR, "spin_milk", 1, PRIYA)

    assert dao.get_by_group(GROUP_ID) == []


def test_failed_remote_remove_keeps_the_local_row(session):
    """The item is still in Swiggy's cart, so it must stay visible locally."""
    session.add(Group(group_id=GROUP_ID, address_id=ADDR))
    session.add(Account(phone=PRIYA, name="Priya"))
    session.commit()
    dao = ItemCartDAO(session)
    working = MockInstamartClient()
    svc = CartService(working, dao)
    svc.add(GROUP_ID, ADDR, "spin_milk", 1, PRIYA)

    svc._client = _RejectingClient()
    with pytest.raises(InstamartDomainError):
        svc.remove(GROUP_ID, ADDR, "spin_milk")

    assert [i.swiggy_item_id for i in dao.get_by_group(GROUP_ID)] == ["spin_milk"]


def test_full_demo_script_runs_clean(svc):
    """Walks the locked demo script's cart beats end to end."""
    svc.add(GROUP_ID, ADDR, "spin_milk", 1, PRIYA)
    svc.add(GROUP_ID, ADDR, "spin_detergent", 1, RAHUL)
    dup = svc.add(GROUP_ID, ADDR, "spin_milk", 1, RAHUL)  # money shot
    assert dup.status == AddStatus.DUPLICATE
    assert dup.existing_requested_by == PRIYA
    svc.add(GROUP_ID, ADDR, "spin_chips", 1, PRIYA)
    svc.remove(GROUP_ID, ADDR, "spin_detergent")
    names = {l.name for l in svc.items(GROUP_ID)}
    assert names == {"Amul Taaza Milk 1L", "Lay's Classic Salted 52g"}
