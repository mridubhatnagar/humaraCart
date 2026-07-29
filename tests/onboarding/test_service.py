"""OnboardingService tests: holder OAuth completion, address selection, JWT invite/join."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from app.accounts.dao import AccountDAO
from app.groups.dao import GroupAccountDAO, GroupDAO
from app.groups.models import Role
from app.instamart.mock import MockInstamartClient
from app.invites.dao import InviteTokenDAO
from app.invites.jwt_tokens import sign
from app.onboarding.service import OnboardingService
from app.settings import Settings
from app.whatsapp.console_messenger import ConsoleMessenger

PHONE = "+919812345678"
MEMBER_PHONE = "+919887654321"


@pytest.fixture
def settings():
    return Settings(
        token_encryption_key="unused",
        twilio_account_sid="unused",
        twilio_auth_token="unused",
        twilio_whatsapp_from="+10000000000",
        jwt_secret="test-secret",
        oauth_redirect_uri="https://example.test/oauth/callback",
    )


@pytest.fixture
def account_dao(session):
    return AccountDAO(session, Fernet(Fernet.generate_key()))


@pytest.fixture
def group_dao(session):
    return GroupDAO(session)


@pytest.fixture
def group_account_dao(session):
    return GroupAccountDAO(session)


@pytest.fixture
def invite_token_dao(session):
    return InviteTokenDAO(session)


@pytest.fixture
def messenger():
    return ConsoleMessenger()


@pytest.fixture
def pending_verifiers():
    return {}


@pytest.fixture
def svc(
    account_dao,
    group_dao,
    group_account_dao,
    invite_token_dao,
    messenger,
    settings,
    pending_verifiers,
):
    return OnboardingService(
        account_dao=account_dao,
        group_dao=group_dao,
        group_account_dao=group_account_dao,
        invite_token_dao=invite_token_dao,
        messenger=messenger,
        settings=settings,
        pending_verifiers=pending_verifiers,
        client_factory=lambda token: MockInstamartClient(),
    )


def _onboard_as_holder(svc, pending_verifiers, settings, messenger, phone=PHONE):
    """Test helper: run a holder through OAuth completion, landing them at address-selection."""
    pending_verifiers[phone] = "verifier123"
    state = sign({"phone": phone}, settings.jwt_secret, timedelta(minutes=10))
    with patch(
        "app.onboarding.service.exchange_code_for_token", return_value="real-tok"
    ):
        svc.complete_holder_oauth("auth-code", state)
    messenger.sent.clear()


def test_new_sender_gets_onboarding_link(svc, messenger):
    svc.handle_message(PHONE, "hi")
    assert len(messenger.sent) == 1
    to, text = messenger.sent[0]
    assert to == PHONE
    assert "auth/authorize" in text


def test_complete_holder_oauth_creates_group_and_asks_for_address(
    svc, messenger, settings, pending_verifiers
):
    pending_verifiers[PHONE] = "verifier123"
    state = sign({"phone": PHONE}, settings.jwt_secret, timedelta(minutes=10))
    with patch(
        "app.onboarding.service.exchange_code_for_token", return_value="real-tok"
    ) as exchange:
        svc.complete_holder_oauth("auth-code", state)
    exchange.assert_called_once_with(
        "auth-code", "verifier123", settings.oauth_redirect_uri
    )
    assert PHONE not in pending_verifiers  # consumed
    to, text = messenger.sent[-1]
    assert to == PHONE
    assert "221B Baker Street" in text  # MockInstamartClient's fixed address


def test_complete_holder_oauth_with_unknown_state_does_nothing(
    svc, messenger, settings
):
    state = sign({"phone": PHONE}, settings.jwt_secret, timedelta(minutes=10))
    with patch("app.onboarding.service.exchange_code_for_token") as exchange:
        svc.complete_holder_oauth("auth-code", state)
    exchange.assert_not_called()
    assert messenger.sent == []


def test_address_selection_sets_group_address(
    svc, messenger, settings, pending_verifiers, group_dao, group_account_dao
):
    _onboard_as_holder(svc, pending_verifiers, settings, messenger)
    svc.handle_message(PHONE, "1")

    group_id = group_account_dao.get_by_account(PHONE)[0].group_id
    group = group_dao.get_by_id(group_id)
    assert group.address_id == "addr_home"
    assert "Household created" in messenger.sent[-1][1]


@pytest.mark.parametrize(
    "bad_reply",
    [
        pytest.param("banana", id="not-a-number"),
        pytest.param("9", id="out-of-range-number"),
    ],
)
def test_an_unusable_choice_reshows_the_list(
    svc, messenger, settings, pending_verifiers, bad_reply
):
    """The list is otherwise printed only once, right after OAuth — so anyone
    replying with anything unexpected gets asked for a number they can no
    longer see."""
    _onboard_as_holder(svc, pending_verifiers, settings, messenger)
    svc.handle_message(PHONE, bad_reply)

    text = messenger.sent[-1][1]
    assert "221B Baker Street" in text  # the options, not just a scolding
    assert "Reply with the number" in text


def test_pending_address_shows_options_without_going_through_oauth(
    svc, messenger, settings, pending_verifiers
):
    """A household seeded without an address must still get the choices."""
    _onboard_as_holder(svc, pending_verifiers, settings, messenger)
    messenger.sent.clear()

    svc.handle_message(PHONE, "add milk")

    assert "221B Baker Street" in messenger.sent[-1][1]


def test_invite_requires_holder_role(svc, messenger, account_dao):
    from app.accounts.models import Account

    account_dao.create(Account(phone=PHONE))
    svc.handle_message(PHONE, "invite")
    assert "account holder" in messenger.sent[-1][1]


def test_invite_generates_wa_me_link_for_holder(
    svc, messenger, settings, pending_verifiers
):
    _onboard_as_holder(svc, pending_verifiers, settings, messenger)
    svc.handle_message(PHONE, "invite")
    assert "wa.me" in messenger.sent[-1][1]


def test_full_invite_join_flow(
    svc, messenger, settings, pending_verifiers, group_account_dao
):
    _onboard_as_holder(svc, pending_verifiers, settings, messenger)
    group_id = group_account_dao.get_by_account(PHONE)[0].group_id

    token = sign(
        {"group_id": group_id, "token_id": "t1"},
        settings.jwt_secret,
        timedelta(hours=24),
    )
    svc.handle_message(MEMBER_PHONE, token)

    memberships = group_account_dao.get_by_account(MEMBER_PHONE)
    assert len(memberships) == 1
    assert memberships[0].role == Role.MEMBER
    assert memberships[0].group_id == group_id
    assert "Welcome to HumaraCart" in messenger.sent[-1][1]


def test_invite_token_replay_is_rejected(
    svc, messenger, settings, pending_verifiers, group_account_dao
):
    _onboard_as_holder(svc, pending_verifiers, settings, messenger)
    group_id = group_account_dao.get_by_account(PHONE)[0].group_id

    token = sign(
        {"group_id": group_id, "token_id": "t1"},
        settings.jwt_secret,
        timedelta(hours=24),
    )
    svc.handle_message(MEMBER_PHONE, token)
    messenger.sent.clear()
    svc.handle_message(MEMBER_PHONE, token)  # replay
    assert "already been used" in messenger.sent[-1][1]


def test_invalid_invite_token_is_rejected(svc, messenger):
    svc.handle_message(MEMBER_PHONE, "not.a.validtoken")
    assert "invalid or expired" in messenger.sent[-1][1]


def test_onboarded_member_is_not_handled_here(
    svc, messenger, settings, pending_verifiers
):
    """Returns False so the dispatcher hands the message to the agent instead."""
    _onboard_as_holder(svc, pending_verifiers, settings, messenger)
    svc.handle_message(PHONE, "1")  # completes address selection
    messenger.sent.clear()

    handled = svc.handle_message(PHONE, "add milk")

    assert handled is False
    assert messenger.sent == []
