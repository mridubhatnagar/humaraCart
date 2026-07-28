"""`CartService` — the deterministic guard around the agent's cart-changing MCP calls.

The agent (not built yet — M5) resolves *what* to add via `search_products`
directly against `IInstamartClient`; by the time it calls the guard, the item
is already a resolved `spin_id`. The guard's job is everything Instamart itself
doesn't track: attribution (who requested each item), dedup, and guaranteeing
every `update_cart` call is a correct full-replace built from the local
`ItemCart` set (DB_DESIGN.md) — never a hand-crafted delta, so a silently
expired Swiggy cart self-heals on the next write.

Per-group locking serializes the read-modify-write: SQLite alone doesn't cover
this, since the network call to Swiggy sits between the local read and the
local write completing. One lock per group_id, not a single global lock, so
unrelated households don't block each other.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum

from app.cart.dao import IItemCartDAO
from app.cart.models import ItemCart
from app.instamart.client import IInstamartClient
from app.instamart.types import CartItemRequest


class AddStatus(str, Enum):
    ADDED = "added"
    DUPLICATE = "duplicate"  # already on the shared list — the money shot


class RemoveStatus(str, Enum):
    REMOVED = "removed"
    NOT_IN_CART = "not_in_cart"


@dataclass
class AddResult:
    status: AddStatus
    # For DUPLICATE: who originally added the item.
    existing_requested_by: str | None = None


@dataclass
class RemoveResult:
    status: RemoveStatus


@dataclass
class CartLine:
    """Local `ItemCart` row reconciled with live Swiggy data for display.

    `name`/`price` come from the live cart (`get_cart`), not storage — if
    Swiggy's cart doesn't have this item (e.g. it expired), they fall back to
    the spin_id and `None` rather than failing the whole display.
    """

    spin_id: str
    name: str
    quantity: int
    price: float | None
    requested_by: str


class CartService:
    def __init__(self, client: IInstamartClient, item_cart_dao: IItemCartDAO) -> None:
        self._client = client
        self._item_cart_dao = item_cart_dao
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def add(
        self,
        group_id: str,
        address_id: str,
        spin_id: str,
        quantity: int,
        requested_by: str,
    ) -> AddResult:
        with self._lock_for(group_id):
            existing = self._item_cart_dao.get_by_group_and_item(group_id, spin_id)
            if existing is not None:
                return AddResult(
                    AddStatus.DUPLICATE, existing_requested_by=existing.requested_by
                )

            self._item_cart_dao.create(
                ItemCart(
                    group_id=group_id,
                    swiggy_item_id=spin_id,
                    quantity=quantity,
                    requested_by=requested_by,
                )
            )
            try:
                self._sync_remote(group_id, address_id)
            except Exception:
                # Local is the source of truth for every future full-replace,
                # so a row Swiggy rejected must not survive — it would be
                # re-sent on every subsequent write and keep failing.
                self._item_cart_dao.delete(f"{group_id}:{spin_id}")
                raise
            return AddResult(AddStatus.ADDED)

    def remove(self, group_id: str, address_id: str, spin_id: str) -> RemoveResult:
        with self._lock_for(group_id):
            existing = self._item_cart_dao.get_by_group_and_item(group_id, spin_id)
            if existing is None:
                return RemoveResult(RemoveStatus.NOT_IN_CART)

            self._item_cart_dao.delete(f"{group_id}:{spin_id}")
            try:
                if self._item_cart_dao.get_by_group(group_id):
                    self._sync_remote(group_id, address_id)
                else:
                    self._client.clear_cart()
            except Exception:
                # Put it back: the item is still in Swiggy's cart, so dropping
                # it locally would hide it from the user and from the next
                # full-replace payload.
                self._item_cart_dao.create(
                    ItemCart(
                        group_id=group_id,
                        swiggy_item_id=spin_id,
                        quantity=existing.quantity,
                        requested_by=existing.requested_by,
                    )
                )
                raise
            return RemoveResult(RemoveStatus.REMOVED)

    def items(self, group_id: str) -> list[CartLine]:
        local_items = self._item_cart_dao.get_by_group(group_id)
        live_by_spin_id = {i.spin_id: i for i in self._client.get_cart().items}
        lines = []
        for local in local_items:
            live = live_by_spin_id.get(local.swiggy_item_id)
            lines.append(
                CartLine(
                    spin_id=local.swiggy_item_id,
                    name=live.name if live else local.swiggy_item_id,
                    quantity=local.quantity,
                    price=live.price if live else None,
                    requested_by=local.requested_by,
                )
            )
        return lines

    def total(self, group_id: str) -> float:
        """What Swiggy says is payable — their number, not our arithmetic.

        Summing item prices ourselves understates it badly: handling, small-cart,
        delivery and GST are all Swiggy's to state, and a ₹35 cart really costs
        ₹102. Fees are not ours to recompute or predict.
        """
        return self._client.get_cart().to_pay or 0

    def _sync_remote(self, group_id: str, address_id: str) -> None:
        local_items = self._item_cart_dao.get_by_group(group_id)
        payload = [
            CartItemRequest(spin_id=i.swiggy_item_id, quantity=i.quantity)
            for i in local_items
        ]
        self._client.update_cart(address_id, payload)

    def _lock_for(self, group_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(group_id, threading.Lock())
