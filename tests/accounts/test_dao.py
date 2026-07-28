"""AccountDAO tests: CRUD contract + the encrypt-at-rest guarantee."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.accounts.dao import AccountDAO
from app.accounts.models import Account

HOLDER_PHONE = "+919812345678"
MEMBER_PHONE = "+919887654321"


@pytest.fixture
def dao(session):
    return AccountDAO(session, Fernet(Fernet.generate_key()))


def test_create_persists_a_row(session, dao):
    """Checked via a raw `session.get()`, bypassing the DAO's own read path entirely."""
    dao.create(Account(phone=HOLDER_PHONE, name="Priya"))
    assert session.get(Account, HOLDER_PHONE) is not None


def test_create_and_get_roundtrip(dao):
    dao.create(
        Account(phone=HOLDER_PHONE, name="Priya", instamart_access_token="tok-abc")
    )
    found = dao.get_by_id(HOLDER_PHONE)
    assert found.name == "Priya"
    assert found.instamart_access_token == "tok-abc"


def test_get_by_phone_is_an_alias(dao):
    dao.create(Account(phone=HOLDER_PHONE, name="Priya"))
    assert dao.get_by_phone(HOLDER_PHONE).name == "Priya"


def test_get_missing_returns_none(dao):
    assert dao.get_by_id("+910000000000") is None


def test_member_has_no_token(dao):
    dao.create(Account(phone=MEMBER_PHONE, name="Rahul"))
    found = dao.get_by_id(MEMBER_PHONE)
    assert found.instamart_access_token is None
    assert found.instamart_refresh_token is None


def test_update_changes_token(dao):
    dao.create(Account(phone=HOLDER_PHONE, name="Priya", instamart_access_token="old"))
    dao.update(Account(phone=HOLDER_PHONE, name="Priya", instamart_access_token="new"))
    assert dao.get_by_id(HOLDER_PHONE).instamart_access_token == "new"


def test_delete_removes_account(dao):
    dao.create(Account(phone=HOLDER_PHONE, name="Priya"))
    dao.delete(HOLDER_PHONE)
    assert dao.get_by_id(HOLDER_PHONE) is None


def test_token_is_encrypted_at_rest(session, dao):
    plaintext = "super-secret-bearer-token"
    dao.create(
        Account(phone=HOLDER_PHONE, name="Priya", instamart_access_token=plaintext)
    )

    raw_row = session.get(Account, HOLDER_PHONE)
    assert raw_row.instamart_access_token != plaintext
    assert raw_row.instamart_access_token is not None

    # A different key can't decrypt it — proves it's real Fernet ciphertext,
    # not a reversible encoding.
    other_dao = AccountDAO(session, Fernet(Fernet.generate_key()))
    with pytest.raises(Exception):
        other_dao.get_by_id(HOLDER_PHONE)


def test_created_entity_returned_unmutated(dao):
    """The caller's own object must keep its plaintext token after create()."""
    entity = Account(phone=HOLDER_PHONE, name="Priya", instamart_access_token="tok-abc")
    returned = dao.create(entity)
    assert returned.instamart_access_token == "tok-abc"
    assert entity.instamart_access_token == "tok-abc"
