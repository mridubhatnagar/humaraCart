"""GroupDAO and GroupAccountDAO tests: CRUD contract + role/holder lookups."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.accounts.models import Account
from app.groups.dao import GroupAccountDAO, GroupDAO
from app.groups.models import Group, GroupAccount, Role

GROUP_ID = "g_priya_household"
OTHER_GROUP_ID = "g_other_household"
HOLDER_PHONE = "+919812345678"
MEMBER_PHONE = "+919887654321"


@pytest.fixture
def group_dao(session):
    return GroupDAO(session)


@pytest.fixture
def group_account_dao(session):
    session.add(Group(group_id=GROUP_ID, address_id=None))
    session.add(Group(group_id=OTHER_GROUP_ID, address_id=None))
    session.add(Account(phone=HOLDER_PHONE, name="Priya"))
    session.add(Account(phone=MEMBER_PHONE, name="Rahul"))
    session.commit()
    return GroupAccountDAO(session)


def test_create_persists_a_row(session, group_dao):
    """Checked via a raw `session.get()`, bypassing the DAO's own read path entirely."""
    group_dao.create(Group(group_id=GROUP_ID, address_id=None))
    assert session.get(Group, GROUP_ID) is not None


def test_create_and_get_roundtrip(group_dao):
    group_dao.create(Group(group_id=GROUP_ID, address_id=None))
    found = group_dao.get_by_id(GROUP_ID)
    assert found.group_id == GROUP_ID
    assert found.address_id is None


def test_get_missing_group_returns_none(group_dao):
    assert group_dao.get_by_id("no_such_group") is None


def test_update_sets_address(group_dao):
    group_dao.create(Group(group_id=GROUP_ID, address_id=None))
    group_dao.update(Group(group_id=GROUP_ID, address_id="addr_246301911"))
    assert group_dao.get_by_id(GROUP_ID).address_id == "addr_246301911"


def test_delete_removes_group(group_dao):
    group_dao.create(Group(group_id=GROUP_ID, address_id=None))
    group_dao.delete(GROUP_ID)
    assert group_dao.get_by_id(GROUP_ID) is None


def test_create_persists_a_membership_row(session, group_account_dao):
    """Checked via a raw `session.get()`, bypassing the DAO's own read path entirely."""
    group_account_dao.create(
        GroupAccount(group_id=GROUP_ID, account_id=HOLDER_PHONE, role=Role.HOLDER)
    )
    assert session.get(GroupAccount, (GROUP_ID, HOLDER_PHONE)) is not None


def test_create_and_get_by_group_and_account(group_account_dao):
    group_account_dao.create(
        GroupAccount(group_id=GROUP_ID, account_id=HOLDER_PHONE, role=Role.HOLDER)
    )
    found = group_account_dao.get_by_group_and_account(GROUP_ID, HOLDER_PHONE)
    assert found.role == Role.HOLDER


def test_get_by_id_uses_composite_convention(group_account_dao):
    group_account_dao.create(
        GroupAccount(group_id=GROUP_ID, account_id=HOLDER_PHONE, role=Role.HOLDER)
    )
    found = group_account_dao.get_by_id(f"{GROUP_ID}:{HOLDER_PHONE}")
    assert found.account_id == HOLDER_PHONE


def test_get_by_group_returns_all_members(group_account_dao):
    group_account_dao.create(
        GroupAccount(group_id=GROUP_ID, account_id=HOLDER_PHONE, role=Role.HOLDER)
    )
    group_account_dao.create(
        GroupAccount(group_id=GROUP_ID, account_id=MEMBER_PHONE, role=Role.MEMBER)
    )
    members = {ga.account_id for ga in group_account_dao.get_by_group(GROUP_ID)}
    assert members == {HOLDER_PHONE, MEMBER_PHONE}


def test_get_by_account_finds_membership_across_groups(group_account_dao):
    """The same person can be holder in one group and member in another (DB_DESIGN.md)."""
    group_account_dao.create(
        GroupAccount(group_id=GROUP_ID, account_id=HOLDER_PHONE, role=Role.HOLDER)
    )
    group_account_dao.create(
        GroupAccount(group_id=OTHER_GROUP_ID, account_id=HOLDER_PHONE, role=Role.MEMBER)
    )
    memberships = group_account_dao.get_by_account(HOLDER_PHONE)
    by_group = {m.group_id: m.role for m in memberships}
    assert by_group == {GROUP_ID: Role.HOLDER, OTHER_GROUP_ID: Role.MEMBER}


def test_get_by_account_empty_for_unknown_person(group_account_dao):
    assert group_account_dao.get_by_account("+910000000000") == []


def test_get_holder_filters_by_role(group_account_dao):
    group_account_dao.create(
        GroupAccount(group_id=GROUP_ID, account_id=HOLDER_PHONE, role=Role.HOLDER)
    )
    group_account_dao.create(
        GroupAccount(group_id=GROUP_ID, account_id=MEMBER_PHONE, role=Role.MEMBER)
    )
    holder = group_account_dao.get_holder(GROUP_ID)
    assert holder.account_id == HOLDER_PHONE


def test_update_changes_role(group_account_dao):
    group_account_dao.create(
        GroupAccount(group_id=GROUP_ID, account_id=MEMBER_PHONE, role=Role.MEMBER)
    )
    group_account_dao.update(
        GroupAccount(group_id=GROUP_ID, account_id=MEMBER_PHONE, role=Role.HOLDER)
    )
    assert (
        group_account_dao.get_by_group_and_account(GROUP_ID, MEMBER_PHONE).role
        == Role.HOLDER
    )


def test_delete_removes_membership(group_account_dao):
    group_account_dao.create(
        GroupAccount(group_id=GROUP_ID, account_id=MEMBER_PHONE, role=Role.MEMBER)
    )
    group_account_dao.delete(f"{GROUP_ID}:{MEMBER_PHONE}")
    assert group_account_dao.get_by_group_and_account(GROUP_ID, MEMBER_PHONE) is None


def test_duplicate_membership_rejected(group_account_dao):
    """(group_id, account_id) is the composite PK — a person is in a group at most once."""
    group_account_dao.create(
        GroupAccount(group_id=GROUP_ID, account_id=HOLDER_PHONE, role=Role.HOLDER)
    )
    with pytest.raises(IntegrityError):
        group_account_dao.create(
            GroupAccount(group_id=GROUP_ID, account_id=HOLDER_PHONE, role=Role.MEMBER)
        )


def test_membership_requires_existing_account(group_account_dao):
    """FK enforcement (PRAGMA foreign_keys=ON) rejects an orphaned account_id."""
    with pytest.raises(IntegrityError):
        group_account_dao.create(
            GroupAccount(
                group_id=GROUP_ID, account_id="+910000000000", role=Role.MEMBER
            )
        )
