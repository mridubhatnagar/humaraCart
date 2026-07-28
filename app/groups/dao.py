"""`Group` and `GroupAccount` DAOs — interface and implementation together.

`GroupAccount`'s primary key is composite (`group_id`, `account_id`); its
`get_by_id`/`update`/`delete` accept that pair joined as
`"{group_id}:{account_id}"` so it still honors `IDAO`'s single-string-id
contract. The real access patterns are the domain methods below —
`get_by_group_and_account` (a pure delegation to `get_by_id`, so it's concrete
on the interface), plus `get_by_group`/`get_holder`, which need real query
access and so stay abstract until a concrete DAO implements them.

Neither entity holds anything encrypted, so — unlike `AccountDAO` — these
return the session-attached row directly rather than a detached copy.
"""

from __future__ import annotations

from abc import abstractmethod

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dao import IDAO
from app.groups.models import Group, GroupAccount, Role


class IGroupDAO(IDAO[Group]):
    pass


class GroupDAO(IGroupDAO):
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, entity: Group) -> Group:
        self._session.add(entity)
        self._session.commit()
        return entity

    def get_by_id(self, id: str) -> Group | None:
        return self._session.get(Group, id)

    def update(self, entity: Group) -> Group:
        row = self._session.get(Group, entity.group_id)
        if row is None:
            raise ValueError(f"no Group for group_id {entity.group_id!r}")
        row.address_id = entity.address_id
        self._session.commit()
        return row

    def delete(self, id: str) -> None:
        row = self._session.get(Group, id)
        if row is not None:
            self._session.delete(row)
            self._session.commit()


class IGroupAccountDAO(IDAO[GroupAccount]):
    def get_by_group_and_account(
        self, group_id: str, account_id: str
    ) -> GroupAccount | None:
        return self.get_by_id(f"{group_id}:{account_id}")

    @abstractmethod
    def get_by_group(self, group_id: str) -> list[GroupAccount]: ...

    @abstractmethod
    def get_by_account(self, account_id: str) -> list[GroupAccount]: ...

    @abstractmethod
    def get_holder(self, group_id: str) -> GroupAccount | None: ...


class GroupAccountDAO(IGroupAccountDAO):
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, entity: GroupAccount) -> GroupAccount:
        self._session.add(entity)
        self._session.commit()
        return entity

    def get_by_id(self, id: str) -> GroupAccount | None:
        group_id, account_id = id.split(":", 1)
        return self._session.get(GroupAccount, (group_id, account_id))

    def get_by_group(self, group_id: str) -> list[GroupAccount]:
        stmt = select(GroupAccount).where(GroupAccount.group_id == group_id)
        return list(self._session.execute(stmt).scalars().all())

    def get_by_account(self, account_id: str) -> list[GroupAccount]:
        stmt = select(GroupAccount).where(GroupAccount.account_id == account_id)
        return list(self._session.execute(stmt).scalars().all())

    def get_holder(self, group_id: str) -> GroupAccount | None:
        stmt = select(GroupAccount).where(
            GroupAccount.group_id == group_id, GroupAccount.role == Role.HOLDER
        )
        return self._session.execute(stmt).scalars().first()

    def update(self, entity: GroupAccount) -> GroupAccount:
        row = self._session.get(GroupAccount, (entity.group_id, entity.account_id))
        if row is None:
            raise ValueError(
                f"no GroupAccount for {entity.group_id!r}/{entity.account_id!r}"
            )
        row.role = entity.role
        self._session.commit()
        return row

    def delete(self, id: str) -> None:
        group_id, account_id = id.split(":", 1)
        row = self._session.get(GroupAccount, (group_id, account_id))
        if row is not None:
            self._session.delete(row)
            self._session.commit()
