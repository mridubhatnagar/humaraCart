"""The `Account` entity — a person with a HumaraCart account (see DB_DESIGN.md).

Covers the account holder and every invited member. `instamart_access_token` /
`instamart_refresh_token` are `NULL` for members (only the holder links
Instamart) and stored encrypted at rest — see `AccountDAO`, which is the only
place that ever sees the plaintext value.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Account(Base):
    __tablename__ = "accounts"

    phone: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    instamart_access_token: Mapped[str | None] = mapped_column(String, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    instamart_refresh_token: Mapped[str | None] = mapped_column(String, nullable=True)
