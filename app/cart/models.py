"""The `ItemCart` entity — the durable, local-as-truth household cart (see DB_DESIGN.md).

Not the cart itself (that lives on Swiggy, ephemeral) — this is what the
deterministic guard rebuilds `update_cart`'s full-replace payload from, so a
silently-expired Swiggy cart self-heals on the next write. Price and product
name are never stored here; they come live from `get_cart`.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ItemCart(Base):
    __tablename__ = "item_carts"

    group_id: Mapped[str] = mapped_column(
        ForeignKey("groups.group_id"), primary_key=True
    )
    swiggy_item_id: Mapped[str] = mapped_column(String, primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_by: Mapped[str] = mapped_column(
        ForeignKey("accounts.phone"), nullable=False
    )
