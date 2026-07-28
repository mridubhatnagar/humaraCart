"""Graph wiring tests: the loop loops, identity is injected, interrupt pauses and resumes.

No real LLM and no network — the model is scripted, the tools are stubs. What's
under test is the graph, not the model's judgement.
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


def test_no_tool_call_ends_immediately():
    model = ScriptedChatModel([reply("Your list is empty.")])
    graph = build_graph(model, {}, MemorySaver())

    result = graph.invoke(initial_state("show list"), config())

    assert result["messages"][-1].content == "Your list is empty."
    assert len(model.received) == 1  # the LLM was called exactly once


def test_tool_call_runs_then_loops_back_to_the_model():
    model = ScriptedChatModel(
        [
            tool_call("search_products", {"query": "milk"}),
            reply("Found Amul Taaza Milk 1L."),
        ]
    )
    calls = []

    def search(args, state):
        calls.append(args)
        return ToolResult(content="1 result: Amul Taaza Milk 1L")

    graph = build_graph(model, {"search_products": search}, MemorySaver())
    result = graph.invoke(initial_state("add 1L milk"), config())

    assert calls == [{"query": "milk"}]
    assert len(model.received) == 2  # called again *after* seeing the tool result
    assert result["messages"][-1].content == "Found Amul Taaza Milk 1L."


def test_loop_runs_more_than_once():
    """Two tool calls in sequence — this is what makes it a loop, not a single shot."""
    model = ScriptedChatModel(
        [
            tool_call("search_products", {"query": "milk"}, "c1"),
            tool_call("update_cart", {"spin_id": "spin_milk", "quantity": 1}, "c2"),
            reply("Added Amul Taaza Milk 1L."),
        ]
    )
    ran = []

    def search(args, state):
        ran.append("search")
        return ToolResult(content="1 result")

    def update(args, state):
        ran.append("update")
        return ToolResult(content="added")

    graph = build_graph(
        model, {"search_products": search, "update_cart": update}, MemorySaver()
    )
    graph.invoke(initial_state("add 1L milk"), config())

    assert ran == ["search", "update"]
    assert len(model.received) == 3


def test_tools_receive_injected_identity_not_model_arguments():
    """group_id/requested_by come from state — the model has no way to supply them."""
    model = ScriptedChatModel(
        [
            tool_call("update_cart", {"spin_id": "spin_milk", "quantity": 1}),
            reply("done"),
        ]
    )
    seen = {}

    def update(args, state):
        seen["args"] = args
        seen["group_id"] = state["group_id"]
        seen["requested_by"] = state["requested_by"]
        return ToolResult(content="added")

    graph = build_graph(model, {"update_cart": update}, MemorySaver())
    graph.invoke(initial_state("add milk"), config())

    assert seen["group_id"] == GROUP_ID
    assert seen["requested_by"] == PRIYA
    assert "group_id" not in seen["args"]
    assert "requested_by" not in seen["args"]


def test_unknown_tool_is_reported_not_crashed():
    model = ScriptedChatModel([tool_call("teleport", {}), reply("sorry")])
    graph = build_graph(model, {}, MemorySaver())

    result = graph.invoke(initial_state("teleport me"), config())

    tool_messages = [m for m in result["messages"] if m.type == "tool"]
    assert "Unknown tool: teleport" in tool_messages[0].content


def test_multiple_variants_pause_the_graph_for_a_human():
    options = [
        {"spin_id": "a", "label": "Amul 1L"},
        {"spin_id": "b", "label": "Amul 500ml"},
    ]
    model = ScriptedChatModel([tool_call("search_products", {"query": "milk"})])

    def search(args, state):
        return ToolResult(content="2 results", options=options)

    graph = build_graph(model, {"search_products": search}, MemorySaver())
    result = graph.invoke(initial_state("add milk"), config())

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["kind"] == "choose_variant"
    assert payload["options"] == options


def test_numeric_choice_is_resolved_to_a_spin_id_by_code():
    """The model only sees "2"; mapping that to a product id must not be its job."""
    options = [
        {"spin_id": "big", "label": "Amul Gold 500 ml x 4", "price": 131},
        {"spin_id": "small", "label": "Amul Gold 500 ml", "price": 32},
    ]
    model = ScriptedChatModel(
        [tool_call("search_products", {"query": "milk"}), reply("Added.")]
    )

    def search(args, state):
        return ToolResult(content="2 options", options=options)

    graph = build_graph(model, {"search_products": search}, MemorySaver())
    graph.invoke(initial_state("add milk"), config())
    result = graph.invoke(Command(resume="2"), config())

    resumed = [m for m in result["messages"] if "I choose" in str(m.content)]
    assert "spin_id=small" in resumed[0].content
    assert "Amul Gold 500 ml" in resumed[0].content


def test_unresolvable_choice_does_not_invent_a_product():
    options = [{"spin_id": "a", "label": "Amul Gold 500 ml", "price": 32}]
    model = ScriptedChatModel(
        [tool_call("search_products", {"query": "milk"}), reply("Which one?")]
    )

    def search(args, state):
        return ToolResult(content="1 option", options=options)

    graph = build_graph(model, {"search_products": search}, MemorySaver())
    graph.invoke(initial_state("add milk"), config())
    result = graph.invoke(Command(resume="99"), config())

    resumed = [m for m in result["messages"] if "I said" in str(m.content)]
    assert resumed  # falls back to the raw answer, no spin_id conjured
    assert "spin_id" not in resumed[0].content


def test_resuming_delivers_the_answer_and_continues():
    options = [{"spin_id": "a", "label": "Amul 1L"}]
    model = ScriptedChatModel(
        [
            tool_call("search_products", {"query": "milk"}),
            tool_call("update_cart", {"spin_id": "a", "quantity": 1}),
            reply("Added Amul 1L."),
        ]
    )
    searches = []

    def search(args, state):
        searches.append(args)
        return ToolResult(content="2 results", options=options)

    def update(args, state):
        return ToolResult(content="added")

    graph = build_graph(
        model, {"search_products": search, "update_cart": update}, MemorySaver()
    )
    graph.invoke(initial_state("add milk"), config())

    result = graph.invoke(Command(resume="Amul 1L"), config())

    assert result["messages"][-1].content == "Added Amul 1L."
    assert len(searches) == 1  # the search was NOT re-run on resume
    assert any("Amul 1L" in str(m.content) for m in result["messages"])


def _confirming_checkout(placed: list):
    """Mirrors the real tool: refuses to place until state says confirmed."""

    def checkout(args, state):
        if not state.get("checkout_confirmed"):
            return ToolResult(
                content="Waiting for confirmation.",
                confirm={"to_pay": 340, "items": []},
            )
        placed.append("checkout")
        return ToolResult(content="order placed", consume_confirmation=True)

    return checkout


def test_checkout_pauses_before_placing_the_order():
    model = ScriptedChatModel([tool_call("checkout", {})])
    placed = []

    graph = build_graph(
        model, {"checkout": _confirming_checkout(placed)}, MemorySaver()
    )
    result = graph.invoke(initial_state("checkout"), config())

    assert result["__interrupt__"][0].value["kind"] == "confirm_checkout"
    assert placed == []  # nothing was placed


def test_a_confirmation_is_spent_once_the_order_is_placed():
    """Otherwise the flag stays true and a further checkout call would place a
    second real order that nobody agreed to."""
    model = ScriptedChatModel([tool_call("checkout", {}, "c1"), reply("Done.")])
    placed = []

    graph = build_graph(
        model, {"checkout": _confirming_checkout(placed)}, MemorySaver()
    )
    graph.invoke(initial_state("checkout"), config())

    result = graph.invoke(Command(resume="yes"), config())

    assert placed == ["checkout"]
    assert result["checkout_confirmed"] is False  # consent does not linger


def test_every_tool_call_gets_a_tool_message_even_when_the_tool_raises():
    """A dangling tool_call poisons the thread: OpenAI rejects an assistant
    message whose tool_calls were never answered, on every later turn."""
    model = ScriptedChatModel(
        [tool_call("search_products", {"query": "milk"}), reply("sorry")]
    )

    def exploding(args, state):
        raise RuntimeError("no such table: item_carts")

    graph = build_graph(model, {"search_products": exploding}, MemorySaver())
    result = graph.invoke(initial_state("add milk"), config())

    tool_messages = [m for m in result["messages"] if m.type == "tool"]
    assert len(tool_messages) == 1
    assert "no such table" in tool_messages[0].content


def test_checkout_never_reaches_ask_human_without_a_tool_message():
    """The old routing sent agent -> ask_human directly, leaving the checkout
    tool_call unanswered. Every AI message with tool_calls must be followed by
    matching tool messages."""
    model = ScriptedChatModel([tool_call("checkout", {}, "c1")])
    graph = build_graph(model, {"checkout": _confirming_checkout([])}, MemorySaver())

    result = graph.invoke(initial_state("checkout"), config())

    answered = {m.tool_call_id for m in result["messages"] if m.type == "tool"}
    for message in result["messages"]:
        for call in getattr(message, "tool_calls", None) or []:
            assert call["id"] in answered


def test_history_accumulates_across_turns_on_one_thread():
    """thread_id = group_id, so the household shares one conversation."""
    model = ScriptedChatModel([reply("first"), reply("second")])
    graph = build_graph(model, {}, MemorySaver())

    graph.invoke(initial_state("hello"), config())
    result = graph.invoke({"messages": [("user", "again")]}, config())

    contents = [str(m.content) for m in result["messages"]]
    assert "hello" in contents
    assert "first" in contents
    assert "again" in contents
    assert "second" in contents


def test_separate_households_do_not_share_history():
    model = ScriptedChatModel([reply("priya reply"), reply("other reply")])
    graph = build_graph(model, {}, MemorySaver())

    graph.invoke(initial_state("milk"), config("group_a"))
    result = graph.invoke(initial_state("bread"), config("group_b"))

    contents = [str(m.content) for m in result["messages"]]
    assert "milk" not in contents
    assert "priya reply" not in contents
