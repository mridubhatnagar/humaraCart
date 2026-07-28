"""The `InviteToken` entity — a single-use invite-consumption ledger (see DB_DESIGN.md).

A row's mere existence means the token has been consumed (insert-on-consume,
not insert-on-issue) — the JWT itself carries the group id and expiry and is
verified stateless; this ledger exists only to catch replays.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class InviteToken(Base):
    __tablename__ = "invite_tokens"

    token_id: Mapped[str] = mapped_column(String, primary_key=True)
    consumed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
