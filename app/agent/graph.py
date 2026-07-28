r"""The agent graph: three nodes, and the edges that make it a loop.

    START -> agent -> tools -> agent -> ... -> END
                   \-> ask_human -/

`agent` calls the LLM (OpenAI). `tools` calls Instamart (Swiggy MCP) or the
cart guard. They are separate nodes because control has to bounce between them
repeatedly within a single WhatsApp message — the model must *observe* each
tool result and re-reason before choosing the next step. A single-shot design
cannot handle out-of-stock, not-serviceable or min-order, because those are
only discoverable from a tool's response.

`ask_human` exists solely to call `interrupt()`. It is deliberately its own
node and does no other work: on resume LangGraph re-executes the node from the
top, so anything above the `interrupt()` call would run twice. Putting the ask
inside `tools` would re-issue the Swiggy search — or worse, re-run a checkout.

Tool execution is injected rather than hardcoded so a read can go straight to
the MCP client while a write goes through the deterministic guard.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agent.state import AgentState


@dataclass
class ToolResult:
    """What a tool hands back.

    `options` is set when the result needs a human pick (search returning
    several variants); `confirm` when the tool refused to act until a human
    approves (checkout). Either one routes the graph to `ask_human`.
    `cart_changed` marks a write that actually landed, so the caller knows to
    broadcast rather than reply only to the sender."""

    content: str
    options: list[dict] | None = None
    confirm: dict | None = None
    cart_changed: bool = False
    # Human phrase for what changed ("added Amul Taaza Milk 1L"), so the
    # broadcast can name it rather than saying "updated the cart".
    change: str | None = None
    # Message for the account holder specifically — a member asking to check
    # out gets handed off rather than being allowed to place the order.
    notify_holder: str | None = None
    # Message for the whole household, e.g. an order actually being placed.
    announce: str | None = None
    # Exact text to send the sender, replacing whatever the model composed.
    # Used for order status, which is a fact we know precisely and the model
    # has repeatedly got wrong by reading stale history as success.
    direct_reply: str | None = None
    # Set when an order actually went through, so the confirmation is spent.
    # Otherwise `checkout_confirmed` stays true and a second call would place
    # another real order with nobody agreeing to it.
    consume_confirmation: bool = False
    # The order id checkout just created, remembered so the closing check can
    # confirm *that* order rather than whatever is now most recent.
    order_id: str | None = None


ToolFn = Callable[[dict, AgentState], ToolResult]


def _is_yes(answer: object) -> bool:
    """Decided in code, not by the model — this gates a real payment."""
    return str(answer).strip().lower() in {"yes", "y", "yeah", "yep", "confirm", "ok", "okay"}


def _resolve_choice(answer: object, options: list[dict]) -> dict | None:
    """Map a human's reply onto one of the offered options.

    Accepts a position ("2") or enough of the label to be unambiguous. Returns
    None when it can't tell, so the model can ask again rather than us picking
    something arbitrary.
    """
    text = str(answer).strip()
    if text.isdigit():
        index = int(text) - 1
        return options[index] if 0 <= index < len(options) else None
    matches = [o for o in options if text.lower() in o.get("label", "").lower()]
    return matches[0] if len(matches) == 1 else None


def prune_for_model(messages: list) -> list:
    """Drop the model's own past prose before sending history back to it.

    Its narration is the least reliable thing in the thread and the most
    misread — it will treat "your order is placed" that it said yesterday as
    evidence an order exists. Tool calls and their results are kept, because
    they are the factual record (and because dropping an assistant message
    that carries `tool_calls` without its `ToolMessage` makes OpenAI reject
    the whole history).
    """
    kept = []
    for message in messages:
        is_ai = getattr(message, "type", None) == "ai"
        has_tool_calls = bool(getattr(message, "tool_calls", None))
        if is_ai and not has_tool_calls and message is not messages[-1]:
            continue
        kept.append(message)
    return kept


def build_graph(
    model: BaseChatModel,
    tools: dict[str, ToolFn],
    checkpointer: BaseCheckpointSaver,
    system_prompt: str = "",
):
    def agent_node(state: AgentState) -> dict:
        messages = prune_for_model(list(state["messages"]))
        if system_prompt:
            # Prepended per call rather than stored in state, so it never
            # accumulates in the conversation history.
            messages = [SystemMessage(content=system_prompt)] + messages
        return {"messages": [model.invoke(messages)]}

    def tools_node(state: AgentState) -> dict:
        last = state["messages"][-1]
        messages, pending, confirm = [], None, None
        changed = state.get("cart_changed", False)
        change = state.get("last_change")
        notify, announce, direct = None, None, None
        spent_confirmation = False
        new_order_id = None
        for call in last.tool_calls:
            fn = tools.get(call["name"])
            try:
                if fn is None:
                    result = ToolResult(content=f"Unknown tool: {call['name']}")
                else:
                    result = fn(call["args"], state)
            except Exception as e:
                # Every tool_call MUST get a ToolMessage back. If a tool raises
                # and we let it escape, the checkpoint keeps an assistant
                # message whose tool_calls were never answered, and OpenAI
                # rejects that history on every subsequent turn — poisoning the
                # thread permanently rather than failing one message.
                result = ToolResult(content=f"That failed: {e}")
            if result.options:
                pending = result.options
            if result.confirm:
                confirm = result.confirm
            if result.cart_changed:
                changed = True
            if result.change:
                change = result.change
            if result.notify_holder:
                notify = result.notify_holder
            if result.announce:
                announce = result.announce
            if result.direct_reply:
                direct = result.direct_reply
            if result.consume_confirmation:
                spent_confirmation = True
            if result.order_id:
                new_order_id = result.order_id
            messages.append(
                ToolMessage(content=result.content, tool_call_id=call["id"])
            )
        return {
            "messages": messages,
            "pending_options": pending,
            "pending_confirmation": confirm,
            "cart_changed": changed,
            "last_change": change,
            "notify_holder": notify,
            "announce": announce,
            "direct_reply": direct,
            "checkout_confirmed": (
                False if spent_confirmation else state.get("checkout_confirmed", False)
            ),
            "last_order_id": new_order_id or state.get("last_order_id"),
        }

    def ask_human_node(state: AgentState) -> dict:
        options = state.get("pending_options")
        if options:
            answer = interrupt({"kind": "choose_variant", "options": options})
            chosen = _resolve_choice(answer, options)
            # Resolved here, not by the model: it only sees "2", and mapping
            # that back to a spin_id is exactly the kind of guess that ends up
            # adding the wrong product to a real cart.
            content = (
                f"I choose: {chosen['label']} (spin_id={chosen['spin_id']})"
                if chosen
                else f"I said: {answer}"
            )
            return {
                "messages": [HumanMessage(content=content)],
                "pending_options": None,
            }
        confirmation = state.get("pending_confirmation") or {}
        answer = interrupt({"kind": "confirm_checkout", **confirmation})

        if not _is_yes(answer):
            return {
                "messages": [HumanMessage(content=f"My answer: {answer}")],
                "pending_confirmation": None,
                "checkout_confirmed": False,
            }

        # Re-issue the checkout ourselves rather than routing back to the model
        # and hoping it calls the tool again. Observed live: it read "My answer:
        # YES" and simply announced success without placing anything. A
        # confirmed order is far too important to depend on the model choosing
        # to act.
        return {
            "messages": [
                HumanMessage(content=f"My answer: {answer}"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "checkout",
                            "args": {
                                "payment_method": confirmation.get("payment_method")
                            },
                            "id": f"confirmed_checkout_{uuid4().hex[:8]}",
                        }
                    ],
                ),
            ],
            "pending_confirmation": None,
            "checkout_confirmed": True,
        }

    def after_agent(state: AgentState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    def after_ask_human(state: AgentState) -> str:
        # A confirmed checkout leaves a tool call for us to execute; anything
        # else goes back to the model to respond.
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else "agent"

    def after_tools(state: AgentState) -> str:
        if state.get("pending_options") or state.get("pending_confirmation"):
            return "ask_human"
        return "agent"

    builder = StateGraph(AgentState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", tools_node)
    builder.add_node("ask_human", ask_human_node)

    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", after_agent, {"tools": "tools", END: END})
    builder.add_conditional_edges(
        "tools", after_tools, {"ask_human": "ask_human", "agent": "agent"}
    )
    builder.add_conditional_edges(
        "ask_human", after_ask_human, {"tools": "tools", "agent": "agent"}
    )

    return builder.compile(checkpointer=checkpointer)
