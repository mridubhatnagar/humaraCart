"""ItemCartDAO tests: CRUD contract + the household-scoped bulk operations."""

from __future__ import annotations

import pytest

from app.accounts.models import Account
from app.cart.dao import ItemCartDAO
from app.cart.models import ItemCart
from app.groups.models import Group

GROUP_ID = "g_priya_household"
OTHER_GROUP_ID = "g_other_household"
HOLDER_PHONE = "+919812345678"
MEMBER_PHONE = "+919887654321"


@pytest.fixture
def dao(session):
    session.add(Group(group_id=GROUP_ID, address_id=None))
    session.add(Group(group_id=OTHER_GROUP_ID, address_id=None))
    session.add(Account(phone=HOLDER_PHONE, name="Priya"))
    session.add(Account(phone=MEMBER_PHONE, name="Rahul"))
    session.commit()
    return ItemCartDAO(session)


def test_create_persists_a_row(session, dao):
    """Checked via a raw `session.get()`, bypassing the DAO's own read path entirely."""
    dao.create(
        ItemCart(
            group_id=GROUP_ID,
            swiggy_item_id="spin_milk",
            quantity=1,
            requested_by=HOLDER_PHONE,
        )
    )
    assert session.get(ItemCart, (GROUP_ID, "spin_milk")) is not None


def test_create_and_get_by_group_and_item(dao):
    dao.create(
        ItemCart(
            group_id=GROUP_ID,
            swiggy_item_id="spin_milk",
            quantity=1,
            requested_by=HOLDER_PHONE,
        )
    )
    found = dao.get_by_group_and_item(GROUP_ID, "spin_milk")
    assert found.quantity == 1
    assert found.requested_by == HOLDER_PHONE


def test_get_by_id_uses_composite_convention(dao):
    dao.create(
        ItemCart(
            group_id=GROUP_ID,
            swiggy_item_id="spin_milk",
            quantity=1,
            requested_by=HOLDER_PHONE,
        )
    )
    found = dao.get_by_id(f"{GROUP_ID}:spin_milk")
    assert found.swiggy_item_id == "spin_milk"


def test_get_by_group_returns_the_full_local_cart(dao):
    dao.create(
        ItemCart(
            group_id=GROUP_ID,
            swiggy_item_id="spin_milk",
            quantity=1,
            requested_by=HOLDER_PHONE,
        )
    )
    dao.create(
        ItemCart(
            group_id=GROUP_ID,
            swiggy_item_id="spin_chips",
            quantity=2,
            requested_by=MEMBER_PHONE,
        )
    )
    items = {i.swiggy_item_id for i in dao.get_by_group(GROUP_ID)}
    assert items == {"spin_milk", "spin_chips"}


def test_households_are_isolated(dao):
    dao.create(
        ItemCart(
            group_id=GROUP_ID,
            swiggy_item_id="spin_milk",
            quantity=1,
            requested_by=HOLDER_PHONE,
        )
    )
    assert dao.get_by_group(OTHER_GROUP_ID) == []


def test_update_changes_quantity(dao):
    dao.create(
        ItemCart(
            group_id=GROUP_ID,
            swiggy_item_id="spin_milk",
            quantity=1,
            requested_by=HOLDER_PHONE,
        )
    )
    dao.update(
        ItemCart(
            group_id=GROUP_ID,
            swiggy_item_id="spin_milk",
            quantity=3,
            requested_by=HOLDER_PHONE,
        )
    )
    assert dao.get_by_group_and_item(GROUP_ID, "spin_milk").quantity == 3


def test_delete_removes_one_item(dao):
    dao.create(
        ItemCart(
            group_id=GROUP_ID,
            swiggy_item_id="spin_milk",
            quantity=1,
            requested_by=HOLDER_PHONE,
        )
    )
    dao.delete(f"{GROUP_ID}:spin_milk")
    assert dao.get_by_group_and_item(GROUP_ID, "spin_milk") is None


def test_delete_all_for_group_clears_the_cart(dao):
    dao.create(
        ItemCart(
            group_id=GROUP_ID,
            swiggy_item_id="spin_milk",
            quantity=1,
            requested_by=HOLDER_PHONE,
        )
    )
    dao.create(
        ItemCart(
            group_id=GROUP_ID,
            swiggy_item_id="spin_chips",
            quantity=1,
            requested_by=MEMBER_PHONE,
        )
    )
    dao.delete_all_for_group(GROUP_ID)
    assert dao.get_by_group(GROUP_ID) == []
