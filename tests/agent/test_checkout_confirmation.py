"""Confirming an order must actually place it.

Observed live: after the user replied YES, the model read "My answer: YES" and
announced success without calling checkout again. Nothing was placed. A
confirmed order is far too important to depend on the model choosing to act, so
the graph re-issues the call itself.
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.graph import ToolResult, build_graph
from tests.agent.scripted_model import ScriptedChatModel, reply, tool_call

GROUP_ID = "g_priya_household"
ADDR = "addr_home"
PRIYA = "+919812345678"


def initial_state(text: str) -> dict:
    return {
        "messages": [("user", text)],
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


def config(thread: str = GROUP_ID) -> dict:
    return {"configurable": {"thread_id": thread}}


def confirming_checkout(placed: list):
    def checkout(args, state):
        if not state.get("checkout_confirmed"):
            # Echo the requested method, as the real tool does — the graph
            # reads it back out of the confirm payload after the pause.
            return ToolResult(
                content="Waiting for confirmation.",
                confirm={
                    "to_pay": 170.0,
                    "payment_method": args.get("payment_method"),
                    "items": [],
                },
            )
        placed.append(args.get("payment_method"))
        return ToolResult(
            content="Order placed.", direct_reply="Order placed. Order id o1."
        )

    return checkout


@pytest.mark.parametrize(
    "payment_method,resume_answer",
    [
        pytest.param("UPI", "YES", id="uppercase-yes"),
        pytest.param("COD", "yes", id="lowercase-yes"),
    ],
)
def test_yes_actually_places_the_order_without_the_model_acting(
    payment_method, resume_answer
):
    """The model is given no chance to re-issue the call — and deliberately
    scripted to reply with prose if it were asked."""
    model = ScriptedChatModel(
        [tool_call("checkout", {"payment_method": payment_method}), reply("anything")]
    )
    placed = []
    graph = build_graph(model, {"checkout": confirming_checkout(placed)}, MemorySaver())

    graph.invoke(initial_state("checkout"), config())
    result = graph.invoke(Command(resume=resume_answer), config())

    assert placed == [payment_method]  # the order genuinely went through
    assert result["direct_reply"] == "Order placed. Order id o1."


@pytest.mark.parametrize(
    "resume_answer",
    [
        pytest.param("NO", id="explicit-no"),
        pytest.param("maybe later", id="ambiguous-is-not-consent"),
    ],
)
def test_anything_but_a_clear_yes_places_nothing(resume_answer):
    """Anything that is not clearly yes must not spend money."""
    model = ScriptedChatModel(
        [tool_call("checkout", {"payment_method": "UPI"}), reply("Okay.")]
    )
    placed = []
    graph = build_graph(model, {"checkout": confirming_checkout(placed)}, MemorySaver())

    graph.invoke(initial_state("checkout"), config())
    result = graph.invoke(Command(resume=resume_answer), config())

    assert placed == []
    assert result["checkout_confirmed"] is False
