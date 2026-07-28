"""Turns a classified Intent into the WhatsApp messages to send back.

Pure and testable: given a household, the sending member, and an Intent, it
drives CartService and returns a list of OutgoingMessage — including the
broadcast to every member after a cart change, which is what keeps the whole
household in sync (the core of the demo). No Twilio or LLM here.
"""

from __future__ import annotations

from app.cart_service import AddStatus, CartService, RemoveStatus
from app.models import Action, Household, Intent, Member, OutgoingMessage


def _format_list(service: CartService, household_id: str) -> str:
    lines = service.items(household_id)
    if not lines:
        return "Current list is empty."
    items = ", ".join(l.product.name for l in lines)
    return f"Current list: {items}"


class Router:
    def __init__(self, service: CartService) -> None:
        self._service = service

    def handle(
        self, household: Household, sender: Member, intent: Intent
    ) -> list[OutgoingMessage]:
        if intent.action == Action.ADD:
            return self._add(household, sender, intent)
        if intent.action == Action.REMOVE:
            return self._remove(household, sender, intent)
        if intent.action == Action.SHOW:
            return [OutgoingMessage(sender, _format_list(self._service, household.id))]
        if intent.action == Action.READY:
            return self._ready(household, sender)
        if intent.action == Action.SEND_LINK:
            return self._send_link(household, sender)
        return [
            OutgoingMessage(
                sender,
                "Sorry, I didn't catch that. Try: add milk, remove chips, "
                "show list, ready to order.",
            )
        ]

    # -- helpers ------------------------------------------------------------

    def _broadcast(self, household: Household, text: str) -> list[OutgoingMessage]:
        return [OutgoingMessage(m, text) for m in household.members]

    def _add(
        self, household: Household, sender: Member, intent: Intent
    ) -> list[OutgoingMessage]:
        res = self._service.add(household.id, intent.item or "", intent.qty, sender.name)
        if res.status == AddStatus.ADDED:
            qty = f" x{intent.qty}" if intent.qty > 1 else ""
            text = (
                f"✅ {sender.name} added {res.product.name}{qty}. "
                f"{_format_list(self._service, household.id)}"
            )
            return self._broadcast(household, text)
        if res.status == AddStatus.DUPLICATE:
            who = res.existing_added_by or "someone"
            return [
                OutgoingMessage(
                    sender,
                    f"👌 {intent.item} is already on the list (added by {who}). "
                    f"{_format_list(self._service, household.id)}",
                )
            ]
        if res.status == AddStatus.UNAVAILABLE:
            return [
                OutgoingMessage(
                    sender, f"⚠️ {res.product.name} is currently unavailable on Instamart."
                )
            ]
        return [
            OutgoingMessage(sender, f"I couldn't find “{intent.item}” on Instamart.")
        ]

    def _remove(
        self, household: Household, sender: Member, intent: Intent
    ) -> list[OutgoingMessage]:
        res = self._service.remove(household.id, intent.item or "", sender.name)
        if res.status == RemoveStatus.REMOVED:
            text = (
                f"❌ {sender.name} removed {res.product.name}. "
                f"{_format_list(self._service, household.id)}"
            )
            return self._broadcast(household, text)
        if res.status == RemoveStatus.NOT_IN_CART:
            return [OutgoingMessage(sender, f"{intent.item} isn't on the list.")]
        return [
            OutgoingMessage(sender, f"I couldn't find “{intent.item}” on Instamart.")
        ]

    def _ready(self, household: Household, sender: Member) -> list[OutgoingMessage]:
        holder = household.account_holder
        msgs = [
            OutgoingMessage(
                holder,
                f"🛒 {sender.name} thinks the cart's ready. "
                f"{_format_list(self._service, household.id)} "
                f"Reply “send cart link” to review.",
            )
        ]
        if sender.phone != holder.phone:
            msgs.append(
                OutgoingMessage(sender, f"Nudged {holder.name} to review the cart. 👍")
            )
        return msgs

    def _send_link(self, household: Household, sender: Member) -> list[OutgoingMessage]:
        holder = household.account_holder
        if sender.phone != holder.phone:
            return [
                OutgoingMessage(
                    sender,
                    f"Only {holder.name} (the account holder) can check out. "
                    f"I've nudged them.",
                )
            ]
        lines = self._service.items(household.id)
        if not lines:
            return [OutgoingMessage(sender, "Your cart is empty — nothing to order yet.")]
        body = "\n".join(
            f"• {l.product.name} x{l.qty} — ₹{l.product.price * l.qty}" for l in lines
        )
        total = self._service.total(household.id)
        return [
            OutgoingMessage(
                sender,
                f"🧾 Your household cart:\n{body}\n\nTotal: ₹{total}\n\n"
                f"Your cart is ready on Instamart 🛒 — open the app to check out.",
            )
        ]
