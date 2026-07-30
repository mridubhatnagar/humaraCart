"""AgentService tests: who receives what, and resume detection.

The graph is faked here — its behaviour is covered in test_graph.py. What's
under test is the WhatsApp-facing decision: broadcast to the household, reply
to the sender, or relay a pending question.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from langchain_core.messages import AIMessage

from app.accounts.dao import AccountDAO
from app.accounts.models import Account
from app.agent.service import AgentService
from app.cart.dao import ItemCartDAO
from app.cart.service import CartService
from app.groups.dao import GroupAccountDAO
from app.groups.models import Group, GroupAccount, Role
from app.instamart.mock import MockInstamartClient
from app.whatsapp.console_messenger import ConsoleMessenger

GROUP_ID = "g_priya_household"
ADDR = "addr_home"
PRIYA = "+919812345678"
RAHUL = "+919887654321"


class FakeInterrupt:
    def __init__(self, value):
        self.value = value


class FakeGraph:
    """Returns a canned result; records what it was invoked with."""

    def __init__(self, result, paused=False, pending_for=None):
        self._result = result
        self._paused = paused
        self._pending_for = pending_for
        self.invoked_with = []

    def invoke(self, payload, config):
        self.invoked_with.append(payload)
        return self._result

    def get_state(self, config):
        class Task:
            interrupts = ("pending",) if self._paused else ()

        class Snapshot:
            tasks = (Task(),)
            values = {"requested_by": self._pending_for}

        return Snapshot()


@pytest.fixture
def wiring(session):
    session.add(Group(group_id=GROUP_ID, address_id=ADDR))
    session.commit()
    account_dao = AccountDAO(session, Fernet(Fernet.generate_key()))
    account_dao.create(Account(phone=PRIYA, name="Priya"))
    account_dao.create(Account(phone=RAHUL, name="Rahul"))
    group_account_dao = GroupAccountDAO(session)
    group_account_dao.create(
        GroupAccount(group_id=GROUP_ID, account_id=PRIYA, role=Role.HOLDER)
    )
    group_account_dao.create(
        GroupAccount(group_id=GROUP_ID, account_id=RAHUL, role=Role.MEMBER)
    )
    client = MockInstamartClient()
    cart_service = CartService(client, ItemCartDAO(session))
    return account_dao, group_account_dao, cart_service, ConsoleMessenger()


def build(wiring, graph):
    account_dao, group_account_dao, cart_service, messenger = wiring
    service = AgentService(
        graph, cart_service, account_dao, group_account_dao, messenger
    )
    return service, messenger, cart_service


def test_cart_change_broadcasts_to_everyone_naming_the_change(wiring):
    graph = FakeGraph(
        {
            "messages": [AIMessage(content="ignored prose")],
            "cart_changed": True,
            "last_change": "added Amul Taaza Milk 1L",
        }
    )
    service, messenger, cart_service = build(wiring, graph)
    cart_service.add(GROUP_ID, ADDR, "spin_milk", 1, PRIYA)

    service.handle(PRIYA, "add milk", GROUP_ID, ADDR)

    assert {to for to, _ in messenger.sent} == {PRIYA, RAHUL}
    text = messenger.sent[0][1]
    assert text.startswith("Priya added Amul Taaza Milk 1L.")
    assert "Amul Taaza Milk 1L x1" in text
    assert "ignored prose" not in text  # broadcast is never the model's words


def test_holder_notification_goes_to_the_holder_not_the_asker(wiring):
    """A member asked to check out: they get the model's reply, the holder gets
    the nudge."""
    graph = FakeGraph(
        {
            "messages": [AIMessage(content="I have nudged the account holder.")],
            "cart_changed": False,
            "notify_holder": "Rahul thinks the cart is ready.",
        }
    )
    service, messenger, _ = build(wiring, graph)

    service.handle(RAHUL, "checkout", GROUP_ID, ADDR)

    delivered = dict(messenger.sent)
    assert delivered[PRIYA] == "Rahul thinks the cart is ready."
    assert delivered[RAHUL] == "I have nudged the account holder."


def test_order_placed_is_announced_to_the_whole_household(wiring):
    graph = FakeGraph(
        {
            "messages": [AIMessage(content="Done, order placed.")],
            "cart_changed": False,
            "announce": "Order placed with Instamart. Order id o1.",
        }
    )
    service, messenger, _ = build(wiring, graph)

    service.handle(PRIYA, "yes", GROUP_ID, ADDR)

    announced = [to for to, text in messenger.sent if "Order id o1" in text]
    assert set(announced) == {PRIYA, RAHUL}


def test_no_cart_change_replies_to_the_sender_only(wiring):
    graph = FakeGraph(
        {"messages": [AIMessage(content="Your cart is empty.")], "cart_changed": False}
    )
    service, messenger, _ = build(wiring, graph)

    service.handle(RAHUL, "show cart", GROUP_ID, ADDR)

    assert messenger.sent == [(RAHUL, "Your cart is empty.")]


def test_pending_question_goes_to_the_sender_only(wiring):
    graph = FakeGraph(
        {
            "messages": [],
            "__interrupt__": [
                FakeInterrupt(
                    {
                        "kind": "choose_variant",
                        "options": [{"label": "Amul 1L", "price": 66}],
                    }
                )
            ],
        }
    )
    service, messenger, _ = build(wiring, graph)

    service.handle(RAHUL, "add milk", GROUP_ID, ADDR)

    assert [to for to, _ in messenger.sent] == [RAHUL]
    assert "Amul 1L" in messenger.sent[0][1]


def test_messages_are_speaker_labelled(wiring):
    graph = FakeGraph({"messages": [AIMessage(content="ok")], "cart_changed": False})
    service, _, _ = build(wiring, graph)

    service.handle(RAHUL, "add milk", GROUP_ID, ADDR)

    sent_content = graph.invoked_with[0]["messages"][0].content
    assert sent_content == "Rahul: add milk"


def test_a_paused_thread_resumes_instead_of_starting_over(wiring):
    graph = FakeGraph(
        {"messages": [AIMessage(content="done")], "cart_changed": False},
        paused=True,
        pending_for=PRIYA,
    )
    service, _, _ = build(wiring, graph)

    service.handle(PRIYA, "2", GROUP_ID, ADDR)

    payload = graph.invoked_with[0]
    assert not isinstance(payload, dict)  # a Command(resume=...), not fresh state


def test_a_different_senders_message_does_not_answer_someone_elses_question(wiring):
    graph = FakeGraph(
        {"messages": [AIMessage(content="done")], "cart_changed": False},
        paused=True,
        pending_for=PRIYA,
    )
    service, messenger, _ = build(wiring, graph)

    service.handle(RAHUL, "2", GROUP_ID, ADDR)

    assert graph.invoked_with == []
    assert "Priya" in messenger.sent[0][1]
