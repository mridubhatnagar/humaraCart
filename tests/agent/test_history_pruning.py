"""History pruning: the model's own prose is the least trustworthy part of a
thread, and the part it most often misreads as fact.

Tool calls and their results stay — they are the factual record, and dropping
an assistant message that carries tool_calls without its ToolMessage makes
OpenAI reject the entire history.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.graph import prune_for_model


def tool_call_message(name: str, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": call_id}])


def test_past_model_prose_is_dropped():
    history = [
        HumanMessage(content="Priya: checkout"),
        AIMessage(content="Your order is placed via Google Pay."),
        HumanMessage(content="Priya: checkout"),
    ]
    kept = prune_for_model(history)

    assert [m.content for m in kept] == ["Priya: checkout", "Priya: checkout"]


def test_user_messages_are_always_kept():
    history = [HumanMessage(content="Priya: add milk")]
    assert prune_for_model(history) == history


def test_tool_calls_and_their_results_survive():
    """These are facts, and an unanswered tool_call breaks the whole request."""
    history = [
        HumanMessage(content="Priya: add milk"),
        tool_call_message("search_products", "c1"),
        ToolMessage(content="2 options found", tool_call_id="c1"),
    ]
    assert prune_for_model(history) == history


def test_no_assistant_tool_call_is_ever_orphaned():
    history = [
        HumanMessage(content="Priya: add milk"),
        tool_call_message("search_products", "c1"),
        ToolMessage(content="found", tool_call_id="c1"),
        AIMessage(content="Added milk."),
        HumanMessage(content="Rahul: show cart"),
        tool_call_message("get_cart", "c2"),
        ToolMessage(content="1 item", tool_call_id="c2"),
    ]
    kept = prune_for_model(history)

    answered = {m.tool_call_id for m in kept if m.type == "tool"}
    for message in kept:
        for call in getattr(message, "tool_calls", None) or []:
            assert call["id"] in answered


def test_the_final_message_is_never_dropped():
    """The last turn is the model's current answer, not stale narration."""
    history = [
        HumanMessage(content="Priya: show cart"),
        AIMessage(content="Your cart is empty."),
    ]
    kept = prune_for_model(history)

    assert kept[-1].content == "Your cart is empty."
