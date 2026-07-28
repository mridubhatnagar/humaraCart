"""`InviteToken` DAO — interface and implementation together.

A row's mere existence means the token was consumed (see the model
docstring), so `is_consumed` is a thin, pure delegation to `get_by_id` —
concrete on the interface, same relationship as `AccountDAO.get_by_phone`.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.dao import IDAO
from app.invites.models import InviteToken


class IInviteTokenDAO(IDAO[InviteToken]):
    def is_consumed(self, token_id: str) -> bool:
        return self.get_by_id(token_id) is not None


class InviteTokenDAO(IInviteTokenDAO):
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, entity: InviteToken) -> InviteToken:
        self._session.add(entity)
        self._session.commit()
        return entity

    def get_by_id(self, id: str) -> InviteToken | None:
        return self._session.get(InviteToken, id)

    def update(self, entity: InviteToken) -> InviteToken:
        row = self._session.get(InviteToken, entity.token_id)
        if row is None:
            raise ValueError(f"no InviteToken for token_id {entity.token_id!r}")
        row.consumed_at = entity.consumed_at
        self._session.commit()
        return row

    def delete(self, id: str) -> None:
        row = self._session.get(InviteToken, id)
        if row is not None:
            self._session.delete(row)
            self._session.commit()
