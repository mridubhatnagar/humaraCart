"""The tools the model can call, and what actually runs when it does.

Two separate things live here, deliberately:

- `TOOL_SCHEMAS` — what the model *sees*. Note what's missing: `address_id`,
  `group_id` and `requested_by` appear nowhere, because the graph injects them
  from state. The model cannot name another household's cart.
- `build_tools(...)` — what actually *runs*. Reads go straight to the MCP
  client; writes go through the M3 guard, which composes the full-replace
  payload from local `ItemCart`. The model never composes that payload, so it
  cannot silently drop a flatmate's item.

Instamart failures are returned as ordinary tool content rather than raised.
That's the point of the loop: the model sees "out of stock" or "not
serviceable" as a result and re-reasons, instead of the graph blowing up.
"""

from __future__ import annotations

import logging

from app.accounts.dao import IAccountDAO
from app.agent.graph import ToolResult
from app.agent.state import AgentState
from app.cart.service import AddStatus, CartService, RemoveStatus
from app.groups.dao import IGroupAccountDAO
from app.instamart.client import (
    IInstamartClient,
    InstamartAuthError,
    InstamartDomainError,
    InstamartUpstreamError,
)

logger = logging.getLogger(__name__)

MAX_VARIANTS_SHOWN = 5
CHECKOUT_CAP = 1000

# Split by role. Paying is the account holder's alone — it is their Instamart
# account and their money — so members never receive those schemas. Gating the
# tool bodies is not enough on its own: the model will happily recite payment
# options it saw earlier in the shared household thread without calling
# anything. Removing the capability is what actually stops it.
SHARED_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search Instamart for a product. Always search before adding anything to the cart.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for, e.g. '1L milk'",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_cart",
            "description": "Add an item to the household cart, or remove it by passing quantity 0.",
            "parameters": {
                "type": "object",
                "properties": {
                    "spin_id": {
                        "type": "string",
                        "description": "The spin_id from a search result",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "How many; 0 removes the item",
                    },
                },
                "required": ["spin_id", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cart",
            "description": "Show what is currently in the household cart.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_order",
            "description": (
                "Check the household's most recent order with Swiggy — whether "
                "it went through, what was in it, and what it cost. Call this "
                "whenever someone says they have paid, says 'done', asks about "
                "an order, or wants to know if it worked."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

HOLDER_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_payment_options",
            "description": "List the payment methods Swiggy offers for this order.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "checkout",
            "description": "Place the order. Only call this after the user has confirmed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "payment_method": {
                        "type": "string",
                        "description": "e.g. UPI or COD",
                    }
                },
            },
        },
    },
]

MEMBER_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "nudge_holder",
            "description": (
                "Ask the account holder to place the order. Use this whenever "
                "this person wants to check out or pay, since only the account "
                "holder can do that."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def schemas_for(is_holder: bool) -> list:
    return SHARED_TOOL_SCHEMAS + (
        HOLDER_TOOL_SCHEMAS if is_holder else MEMBER_TOOL_SCHEMAS
    )


def build_tools(
    client: IInstamartClient,
    cart_service: CartService,
    account_dao: IAccountDAO,
    group_account_dao: IGroupAccountDAO,
) -> dict:
    def _name_for(phone: str) -> str:
        account = account_dao.get_by_phone(phone)
        return account.name if account and account.name else phone

    def _is_holder(group_id: str, phone: str) -> bool:
        holder = group_account_dao.get_holder(group_id)
        return holder is not None and holder.account_id == phone

    def nudge_holder(args: dict, state: AgentState) -> ToolResult:
        """The member-facing counterpart to checkout: the correct action when
        someone who cannot pay asks to."""
        return _nudge_holder(state)

    def _nudge_holder(state: AgentState) -> ToolResult:
        asker = _name_for(state["requested_by"])
        return ToolResult(
            content=(
                "This person is not the account holder, so nothing was placed. "
                "Tell them you have nudged the account holder to place the order."
            ),
            notify_holder=(
                f"{asker} thinks the cart is ready. "
                f"Reply 'checkout' to review and place the order."
            ),
        )

    def search_products(args: dict, state: AgentState) -> ToolResult:
        try:
            variations = client.search_products(state["address_id"], args["query"])
        except (InstamartDomainError, InstamartUpstreamError, InstamartAuthError) as e:
            logger.warning("search_products failed for query %r: %s", args["query"], e)
            return ToolResult(content=f"Instamart could not search right now: {e}")

        available = [v for v in variations if v.available]
        if not variations:
            return ToolResult(content="Nothing matched that search.")
        if not available:
            return ToolResult(content=f"{variations[0].label} is out of stock.")

        if len(available) == 1:
            v = available[0]
            return ToolResult(
                content=f"One match: {v.label} at ₹{v.price} (spin_id={v.spin_id})"
            )

        shown = available[:MAX_VARIANTS_SHOWN]
        listing = "\n".join(
            f"{i}. {v.label} - ₹{v.price} (spin_id={v.spin_id})"
            for i, v in enumerate(shown, 1)
        )
        return ToolResult(
            content=f"{len(shown)} options found:\n{listing}",
            options=[
                {"spin_id": v.spin_id, "label": v.label, "price": v.price}
                for v in shown
            ],
        )

    def _name_of(spin_id: str, group_id: str) -> str:
        for line in cart_service.items(group_id):
            if line.spin_id == spin_id:
                return line.name
        return spin_id

    def update_cart(args: dict, state: AgentState) -> ToolResult:
        spin_id = args["spin_id"]
        quantity = int(args.get("quantity", 1))
        try:
            if quantity <= 0:
                # Read the name before removing it, or it's gone.
                name = _name_of(spin_id, state["group_id"])
                removed = cart_service.remove(
                    state["group_id"], state["address_id"], spin_id
                )
                if removed.status == RemoveStatus.NOT_IN_CART:
                    return ToolResult(content="That item is not in the cart.")
                return ToolResult(
                    content="Removed from the cart.",
                    cart_changed=True,
                    change=f"removed {name}",
                )

            added = cart_service.add(
                state["group_id"],
                state["address_id"],
                spin_id,
                quantity,
                state["requested_by"],
            )
        except (InstamartDomainError, InstamartUpstreamError, InstamartAuthError) as e:
            logger.warning(
                "update_cart failed for spin_id %r in group %r: %s",
                spin_id,
                state["group_id"],
                e,
            )
            return ToolResult(content=f"Instamart rejected the cart update: {e}")

        if added.status == AddStatus.DUPLICATE:
            who = (
                _name_for(added.existing_requested_by)
                if added.existing_requested_by
                else "someone"
            )
            return ToolResult(content=f"Already in the cart, added by {who}.")

        name = _name_of(spin_id, state["group_id"])
        qty = f" x{quantity}" if quantity > 1 else ""
        return ToolResult(
            content="Added to the cart.",
            cart_changed=True,
            change=f"added {name}{qty}",
        )

    def get_cart(args: dict, state: AgentState) -> ToolResult:
        try:
            lines = cart_service.items(state["group_id"])
        except (InstamartDomainError, InstamartUpstreamError, InstamartAuthError) as e:
            logger.warning("get_cart failed for group %r: %s", state["group_id"], e)
            return ToolResult(content=f"Could not read the cart: {e}")
        if not lines:
            return ToolResult(content="Your cart is currently empty.")
        listing = "\n".join(
            f"- {l.name} x{l.quantity} (added by {_name_for(l.requested_by)})"
            for l in lines
        )
        total = cart_service.total(state["group_id"])
        return ToolResult(content=f"{listing}\nTo pay: ₹{total} (includes fees)")

    def check_order(args: dict, state: AgentState) -> ToolResult:
        """Answers "did it go through?" from Swiggy, not from memory.

        A confirmed order is announced to the whole household — it is the
        closing beat, and everyone who contributed to the cart should see it.
        """
        try:
            orders = client.get_orders()
        except (InstamartDomainError, InstamartUpstreamError, InstamartAuthError) as e:
            logger.warning("check_order failed for group %r: %s", state["group_id"], e)
            return ToolResult(content=f"Could not check the order: {e}")
        if not orders:
            return ToolResult(content="No orders found on this account yet.")

        # Match the order we actually placed. An unpaid UPI order disappears
        # from Swiggy's list entirely, so falling back to "most recent" would
        # cheerfully report a week-old delivery as though it just happened.
        placed_id = state.get("last_order_id")
        if placed_id:
            details = next((o for o in orders if o.order_id == placed_id), None)
            if details is None:
                return ToolResult(
                    content=(
                        "That order is not showing on Swiggy. The payment most "
                        "likely did not go through, and nothing was charged."
                    ),
                    direct_reply=(
                        "I cannot see that order on Swiggy — the payment likely "
                        "did not complete, and nothing was charged. Try checkout again."
                    ),
                )
        else:
            details = orders[0]

        listing = "\n".join(f"- {i}" for i in details.items)
        summary = f"Order placed. It should reach you soon.\n\n{listing}"
        if details.total is not None:
            summary += f"\nTotal: ₹{details.total}"

        # Announce on the order being confirmed, not on payment having settled.
        # Swiggy leaves paymentStatus PENDING for a while after a UPI order is
        # confirmed, so waiting for SUCCESS would stay silent exactly when the
        # household most wants to hear.
        cancelled = "cancel" in details.status.lower()
        return ToolResult(
            content=f"{summary}\n(status: {details.status})",
            direct_reply=summary,
            announce=None if cancelled else summary,
        )

    def get_payment_options(args: dict, state: AgentState) -> ToolResult:
        # Gated as well as `checkout`: the model reaches for this one *first*
        # when asked to check out, so gating only `checkout` would let a member
        # walk right up to paying before anything stopped them.
        if not _is_holder(state["group_id"], state["requested_by"]):
            return _nudge_holder(state)
        try:
            options = client.get_payment_options()
        except (InstamartDomainError, InstamartUpstreamError, InstamartAuthError) as e:
            logger.warning(
                "get_payment_options failed for group %r: %s", state["group_id"], e
            )
            return ToolResult(content=f"Could not fetch payment options: {e}")
        if not options:
            return ToolResult(content="Instamart offered no payment methods.")
        listing = "\n".join(
            f"- {o.label} (pass payment_method={o.id})" for o in options
        )
        return ToolResult(
            content=f"Payment methods available:\n{listing}\n"
            f"Pass exactly one of these ids to checkout, nothing else."
        )

    def checkout(args: dict, state: AgentState) -> ToolResult:
        try:
            if not cart_service.items(state["group_id"]):
                return ToolResult(
                    content="Your cart is empty, so there is nothing to order yet."
                )

            if not _is_holder(state["group_id"], state["requested_by"]):
                # Only the account holder can place an order — it is their
                # Instamart account and their money. A member asking for it is
                # a nudge, not an instruction.
                return _nudge_holder(state)

            cart = client.get_cart()
            if cart.to_pay is not None and cart.to_pay >= CHECKOUT_CAP:
                return ToolResult(
                    content=f"The cart is ₹{cart.to_pay}. Swiggy does not allow checkout over "
                    f"₹{CHECKOUT_CAP} here, so this order has to be placed in the Swiggy app."
                )

            if not state.get("checkout_confirmed"):
                # Refuse to place until a human has approved. The graph turns
                # this into an `interrupt`, so the stop is enforced by code and
                # cannot be talked out of by the model.
                return ToolResult(
                    content="Waiting for the user to confirm before placing the order.",
                    confirm={
                        "to_pay": cart.to_pay,
                        "payment_method": args.get("payment_method"),
                        "items": [f"{i.name} x{i.quantity}" for i in cart.items],
                        "bill_lines": cart.bill_lines,
                    },
                )

            result = client.checkout(state["address_id"], args.get("payment_method"))
        except (InstamartDomainError, InstamartUpstreamError, InstamartAuthError) as e:
            logger.error("checkout failed for group %r: %s", state["group_id"], e)
            return ToolResult(content=f"Checkout failed: {e}")

        if result.bridge_url:
            # Deliberately no `announce`: the order is not placed until payment
            # succeeds, and the link itself is the holder's alone — it must
            # never go to the household.
            return ToolResult(
                content="Order created, awaiting payment. The payment link has "
                "already been sent to the user.",
                direct_reply=(
                    f"Almost done. Tap to pay:\n{result.bridge_url}\n\n"
                    f"Once you have paid, reply 'done' and I will confirm the order."
                ),
                consume_confirmation=True,
                order_id=result.order_id,
            )
        if not result.order_id:
            # No link and no order id means nothing was placed. Saying "order
            # placed" here would be a lie the user acts on.
            return ToolResult(
                content=(
                    f"Checkout did not complete (status: {result.status}). "
                    f"No order was placed and nothing was charged."
                ),
                direct_reply=(
                    "That did not go through, and nothing was charged. "
                    "Please try again."
                ),
            )
        return ToolResult(
            announce=f"Order placed with Instamart. Order id {result.order_id}.",
            direct_reply=f"Order placed. Order id {result.order_id}.",
            consume_confirmation=True,
            order_id=result.order_id,
            content=f"Order placed. Status: {result.status}, order id {result.order_id}",
        )

    return {
        "search_products": search_products,
        "update_cart": update_cart,
        "get_cart": get_cart,
        "check_order": check_order,
        "get_payment_options": get_payment_options,
        "checkout": checkout,
        "nudge_holder": nudge_holder,
    }
