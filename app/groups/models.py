"""The `Group` (household) and `GroupAccount` (membership) entities — see DB_DESIGN.md.

`Group` is a household: just an id and the chosen Swiggy delivery address.
`GroupAccount` is the join between `Account` and `Group`, carrying the
person's role in that specific group — the same person can be a holder in
one group and a member in another, so role lives on the membership, not the
account.
"""

from __future__ import annotations

from enum import Enum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Role(str, Enum):
    HOLDER = "holder"
    MEMBER = "member"


class Group(Base):
    __tablename__ = "groups"

    group_id: Mapped[str] = mapped_column(String, primary_key=True)
    address_id: Mapped[str | None] = mapped_column(String, nullable=True)


class GroupAccount(Base):
    __tablename__ = "group_accounts"

    group_id: Mapped[str] = mapped_column(
        ForeignKey("groups.group_id"), primary_key=True
    )
    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.phone"), primary_key=True
    )
    role: Mapped[Role] = mapped_column(SAEnum(Role), nullable=False)
