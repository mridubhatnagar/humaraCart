"""InviteTokenDAO tests: CRUD contract + the single-use-ledger guarantee."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.invites.dao import InviteTokenDAO
from app.invites.models import InviteToken

TOKEN_ID = "inv_abc123"
NOW = datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def dao(session):
    return InviteTokenDAO(session)


def test_create_persists_a_row(session, dao):
    """Checked via a raw `session.get()`, bypassing the DAO's own read path entirely."""
    dao.create(InviteToken(token_id=TOKEN_ID, consumed_at=NOW))
    assert session.get(InviteToken, TOKEN_ID) is not None


def test_create_and_get_roundtrip(dao):
    dao.create(InviteToken(token_id=TOKEN_ID, consumed_at=NOW))
    found = dao.get_by_id(TOKEN_ID)
    assert found.token_id == TOKEN_ID


def test_is_consumed_true_after_creation(dao):
    dao.create(InviteToken(token_id=TOKEN_ID, consumed_at=NOW))
    assert dao.is_consumed(TOKEN_ID) is True


def test_is_consumed_false_for_unknown_token(dao):
    assert dao.is_consumed("never_issued") is False


def test_replay_of_the_same_token_is_rejected(dao):
    """A row's mere existence means consumed — a second insert is a replay."""
    dao.create(InviteToken(token_id=TOKEN_ID, consumed_at=NOW))
    with pytest.raises(IntegrityError):
        dao.create(InviteToken(token_id=TOKEN_ID, consumed_at=NOW))


def test_delete_removes_token(dao):
    dao.create(InviteToken(token_id=TOKEN_ID, consumed_at=NOW))
    dao.delete(TOKEN_ID)
    assert dao.get_by_id(TOKEN_ID) is None
