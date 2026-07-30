"""`AgentService` — the bridge between LangGraph's pause/resume model and WhatsApp.

WhatsApp delivers one message at a time with no notion of a conversation being
mid-flight. LangGraph can sit paused at an `interrupt` indefinitely. So every
inbound message has to answer one question first: is this a new request, or the
answer to something we already asked? That's what `_pending_for` decides, by
checking whether the household's thread has a task waiting on an interrupt —
and, since a pause is a question addressed to one specific person, whether this
sender is the one it was asked to. A different household member's message while
someone else's question is outstanding is never treated as that answer.

Reply routing follows the locked decision: if the cart actually changed, the
whole household gets one identical deterministic message and the model's prose
is discarded — broadcast is never an LLM decision. Otherwise the model's reply
goes to the sender alone.
"""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from app.accounts.dao import IAccountDAO
from app.cart.service import CartService
from app.groups.dao import IGroupAccountDAO
from app.whatsapp.messenger import IMessenger

logger = logging.getLogger(__name__)

RECURSION_LIMIT = 12


class AgentService:
    def __init__(
        self,
        graph,
        cart_service: CartService,
        account_dao: IAccountDAO,
        group_account_dao: IGroupAccountDAO,
        messenger: IMessenger,
    ) -> None:
        self._graph = graph
        self._cart_service = cart_service
        self._account_dao = account_dao
        self._group_account_dao = group_account_dao
        self._messenger = messenger

    def handle(self, sender: str, body: str, group_id: str, address_id: str) -> None:
        config = {
            "configurable": {"thread_id": group_id},
            "recursion_limit": RECURSION_LIMIT,
        }

        pending_for = self._pending_for(config)
        if pending_for is not None and pending_for != sender:
            self._messenger.send(
                sender,
                f"Waiting on a reply from {self._name_for(pending_for)} first — "
                "try again once they've answered.",
            )
            return

        if pending_for is not None:
            payload = Command(resume=body)
        else:
            payload = {
                "messages": [HumanMessage(content=f"{self._name_for(sender)}: {body}")],
                "group_id": group_id,
                "address_id": address_id,
                "requested_by": sender,
                "pending_options": None,
                "pending_confirmation": None,
                "checkout_confirmed": False,
                "cart_changed": False,
                "last_change": None,
                "notify_holder": None,
                "announce": None,
            }

        try:
            result = self._graph.invoke(payload, config)
        except GraphRecursionError:
            logger.error(
                "Agent hit the recursion limit (%d) for group %r, sender %r, body %r",
                RECURSION_LIMIT,
                group_id,
                sender,
                body,
            )
            self._messenger.send(sender, "I got stuck on that one. Could you rephrase?")
            return

        pending = result.get("__interrupt__")
        if pending:
            self._messenger.send(sender, self._render_question(pending[0].value))
            return

        # A message aimed at the holder rather than whoever asked — currently a
        # member being handed off at checkout.
        for_holder = result.get("notify_holder")
        if for_holder:
            self._send_to_holder(group_id, for_holder)

        if result.get("cart_changed"):
            self._broadcast_list(group_id, sender, result.get("last_change"))
            return

        # Order status is a fact we know exactly, so we state it rather than
        # letting the model paraphrase — it has repeatedly read stale history
        # as evidence an order succeeded.
        self._messenger.send(
            sender, result.get("direct_reply") or str(result["messages"][-1].content)
        )

        # Household-wide news (an order actually placed) goes out after the
        # sender's own reply. Never carries a payment link.
        announcement = result.get("announce")
        if announcement:
            self._broadcast(group_id, announcement)

    def _send_to_holder(self, group_id: str, text: str) -> None:
        holder = self._group_account_dao.get_holder(group_id)
        if holder is not None:
            self._messenger.send(holder.account_id, text)

    def _broadcast(self, group_id: str, text: str) -> None:
        recipients = [
            m.account_id for m in self._group_account_dao.get_by_group(group_id)
        ]
        self._messenger.broadcast(recipients, text)

    def _pending_for(self, config: dict) -> str | None:
        """Who a paused thread's outstanding question was addressed to, or
        None if the thread isn't paused."""
        snapshot = self._graph.get_state(config)
        if any(task.interrupts for task in snapshot.tasks):
            return snapshot.values.get("requested_by")
        return None

    def _render_question(self, payload: dict) -> str:
        if payload.get("kind") == "choose_variant":
            options = payload.get("options", [])
            listing = "\n".join(
                f"{i}. {o['label']} - ₹{o['price']}" for i, o in enumerate(options, 1)
            )
            return f"Which one?\n{listing}\n\nReply with the number."

        parts = ["*Your Cart*"]
        items = payload.get("items") or []
        if items:
            parts.append("\n".join(f"- {i}" for i in items))
        # Swiggy's own bill lines, shown as-is: fees and charges are theirs to
        # state, not ours to recompute.
        bill_lines = payload.get("bill_lines") or []
        if bill_lines:
            parts.append("\n".join(f"{label}: {value}" for label, value in bill_lines))
        parts.append(f"To pay: ₹{payload.get('to_pay')}")
        method = payload.get("payment_method")
        if method:
            parts.append(f"Paying by: {method}")
        return (
            "\n\n".join(parts) + "\n\nReply YES to place this order, or NO to cancel."
        )

    def _broadcast_list(
        self, group_id: str, changed_by: str, change: str | None = None
    ) -> None:
        who = self._name_for(changed_by)
        headline = f"{who} {change}." if change else f"{who} updated the cart."

        lines = self._cart_service.items(group_id)
        if lines:
            listing = "\n".join(f"- {l.name} x{l.quantity}" for l in lines)
            total = self._cart_service.total(group_id)
            text = f"{headline}\n\nCurrent cart:\n{listing}\nTo pay: ₹{total}"
        else:
            text = f"{headline}\n\nThe cart is now empty."

        self._broadcast(group_id, text)

    def _name_for(self, phone: str) -> str:
        account = self._account_dao.get_by_phone(phone)
        return account.name if account and account.name else phone
