"""What flows between the graph's nodes.

`messages` needs the `add_messages` reducer. Without it, a node returning
`{"messages": [...]}` would *replace* the history instead of appending to it,
so the conversation would be wiped on every turn.

`group_id` / `address_id` / `requested_by` are injected by the caller and are
invisible to the model — there is no tool parameter it could use to reach
another household's cart.

The last two fields exist to drive the conditional edges:
- `pending_options` is set by the tools node when a result needs a human pick,
  which is what routes us to `ask_human`.
- `checkout_confirmed` stops the checkout loop: `ask_human` returns to `agent`,
  the model re-issues its `checkout` call, and without this flag the edge would
  route straight back to `ask_human` forever.
- `cart_changed` tells the caller a write actually landed, so it can broadcast
  the list to the whole household instead of replying only to the sender.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    group_id: str
    address_id: str
    requested_by: str
    pending_options: list[dict] | None
    pending_confirmation: dict | None
    checkout_confirmed: bool
    cart_changed: bool
    last_change: str | None
    notify_holder: str | None
    announce: str | None
    direct_reply: str | None
    last_order_id: str | None
