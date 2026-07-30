"""ConversationService tests: help, and the onboarding-vs-agent branch."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

from app.accounts.dao import AccountDAO
from app.accounts.models import Account
from app.conversation.service import ConversationService
from app.groups.dao import GroupAccountDAO, GroupDAO
from app.groups.models import Group, GroupAccount, Role
from app.whatsapp.console_messenger import ConsoleMessenger

GROUP_ID = "g_priya_household"
ADDR = "addr_home"
PRIYA = "+919812345678"
STRANGER = "+910000000000"


@pytest.fixture
def wiring(session):
    from cryptography.fernet import Fernet

    session.add(Group(group_id=GROUP_ID, address_id=ADDR))
    session.commit()
    account_dao = AccountDAO(session, Fernet(Fernet.generate_key()))
    account_dao.create(Account(phone=PRIYA, name="Priya"))
    group_account_dao = GroupAccountDAO(session)
    group_account_dao.create(
        GroupAccount(group_id=GROUP_ID, account_id=PRIYA, role=Role.HOLDER)
    )
    return GroupDAO(session), group_account_dao, ConsoleMessenger(), account_dao


def build(wiring, onboarding_handled: bool):
    group_dao, group_account_dao, messenger, account_dao = wiring
    onboarding = MagicMock()
    onboarding.handle_message.return_value = onboarding_handled
    assembler = MagicMock()
    service = ConversationService(
        onboarding=onboarding,
        agent_assembler=assembler,
        group_dao=group_dao,
        group_account_dao=group_account_dao,
        messenger=messenger,
        account_dao=account_dao,
    )
    return service, onboarding, assembler, messenger, account_dao


def test_help_is_answered_without_the_agent_or_onboarding(wiring):
    service, onboarding, assembler, messenger, _ = build(
        wiring, onboarding_handled=False
    )

    service.handle(PRIYA, "help")

    assert len(messenger.sent) == 1
    text = messenger.sent[0][1]
    assert "add milk" in text
    assert "checkout" in text
    onboarding.handle_message.assert_not_called()
    assembler.for_group.assert_not_called()


def test_help_is_case_insensitive_and_trimmed(wiring):
    service, _, _, messenger, _ = build(wiring, onboarding_handled=False)

    service.handle(PRIYA, "  HELP ")

    assert "HumaraCart" in messenger.sent[0][1]


def test_help_works_for_someone_with_no_household(wiring):
    service, _, _, messenger, _ = build(wiring, onboarding_handled=False)

    service.handle(STRANGER, "help")

    assert "add milk" in messenger.sent[0][1]


def test_onboarding_takes_precedence_over_the_agent(wiring):
    service, onboarding, assembler, _, _ = build(wiring, onboarding_handled=True)

    service.handle(PRIYA, "invite")

    onboarding.handle_message.assert_called_once_with(PRIYA, "invite")
    assembler.for_group.assert_not_called()


def test_onboarded_sender_reaches_the_agent(wiring):
    service, _, assembler, _, _ = build(wiring, onboarding_handled=False)

    service.handle(PRIYA, "add milk")

    assembler.for_group.assert_called_once_with(GROUP_ID, PRIYA)
    assembler.for_group.return_value.handle.assert_called_once_with(
        PRIYA, "add milk", GROUP_ID, ADDR
    )


def test_sender_with_no_household_is_told_so(wiring):
    service, _, assembler, messenger, _ = build(wiring, onboarding_handled=False)

    service.handle(STRANGER, "add milk")

    assert "not part of a household" in messenger.sent[0][1]
    assembler.for_group.assert_not_called()


def test_profile_name_fills_in_a_missing_name(wiring):
    """Members who join by invite arrive nameless, so attribution would read
    "added by +9198..." instead of a name."""
    service, _, _, _, account_dao = build(wiring, onboarding_handled=True)
    account_dao.create(Account(phone=STRANGER))

    service.handle(STRANGER, "hi", profile_name="Rahul")

    assert account_dao.get_by_phone(STRANGER).name == "Rahul"


def test_an_existing_name_is_not_overwritten(wiring):
    """WhatsApp display names change on a whim; a name we already have may
    have been set deliberately."""
    service, _, _, _, account_dao = build(wiring, onboarding_handled=True)

    service.handle(PRIYA, "hi", profile_name="Something Else")

    assert account_dao.get_by_phone(PRIYA).name == "Priya"


def test_no_profile_name_changes_nothing(wiring):
    service, _, _, _, account_dao = build(wiring, onboarding_handled=True)

    service.handle(PRIYA, "hi")

    assert account_dao.get_by_phone(PRIYA).name == "Priya"


def test_concurrent_messages_do_not_overlap_in_the_agent():
    """Background tasks run on a thread pool: two inbound messages could
    otherwise reach the agent at the same instant and race on its shared
    LangGraph checkpoint (observed live as a dangling tool_call OpenAI 400).
    The lock must serialize them.

    DAOs are mocked here rather than DB-backed (unlike the other tests in
    this file): the in-memory SQLite `session` fixture isn't safe to hit from
    two real threads at once, and that's not what this test is about."""
    group_account_dao = MagicMock()
    group_account_dao.get_by_account.return_value = [
        GroupAccount(group_id=GROUP_ID, account_id=PRIYA, role=Role.HOLDER)
    ]
    group_dao = MagicMock()
    group_dao.get_by_id.return_value = Group(group_id=GROUP_ID, address_id=ADDR)
    onboarding = MagicMock()
    onboarding.handle_message.return_value = False
    assembler = MagicMock()
    service = ConversationService(
        onboarding=onboarding,
        agent_assembler=assembler,
        group_dao=group_dao,
        group_account_dao=group_account_dao,
        messenger=ConsoleMessenger(),
        account_dao=MagicMock(),
    )

    events: list[tuple[str, str]] = []
    events_guard = threading.Lock()

    def slow_handle(sender, body, group_id, address_id):
        with events_guard:
            events.append(("start", body))
        time.sleep(0.05)
        with events_guard:
            events.append(("end", body))

    assembler.for_group.return_value.handle.side_effect = slow_handle

    t1 = threading.Thread(target=service.handle, args=(PRIYA, "add milk"))
    t2 = threading.Thread(target=service.handle, args=(PRIYA, "add bread"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(events) == 4
    first_body = events[0][1]
    assert events[1] == (
        "end",
        first_body,
    ), "second message started before the first finished"
