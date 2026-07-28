"""`ItemCart` DAO — interface and implementation together.

Composite primary key (`group_id`, `swiggy_item_id`); `get_by_id`/`update`/
`delete` accept that pair joined as `"{group_id}:{swiggy_item_id}"` (same
convention as `GroupAccountDAO`). `get_by_group_and_item` is a pure delegation
to `get_by_id`, so it's concrete on the interface; `get_by_group` (the full
local cart the guard rebuilds `update_cart` from) and `delete_all_for_group`
(cart cleared on order placement) need real query access, so they stay
abstract until a concrete DAO implements them.
"""

from __future__ import annotations

from abc import abstractmethod

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cart.models import ItemCart
from app.core.dao import IDAO


class IItemCartDAO(IDAO[ItemCart]):
    def get_by_group_and_item(
        self, group_id: str, swiggy_item_id: str
    ) -> ItemCart | None:
        return self.get_by_id(f"{group_id}:{swiggy_item_id}")

    @abstractmethod
    def get_by_group(self, group_id: str) -> list[ItemCart]: ...

    @abstractmethod
    def delete_all_for_group(self, group_id: str) -> None: ...


class ItemCartDAO(IItemCartDAO):
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, entity: ItemCart) -> ItemCart:
        self._session.add(entity)
        self._session.commit()
        return entity

    def get_by_id(self, id: str) -> ItemCart | None:
        group_id, swiggy_item_id = id.split(":", 1)
        return self._session.get(ItemCart, (group_id, swiggy_item_id))

    def get_by_group(self, group_id: str) -> list[ItemCart]:
        stmt = select(ItemCart).where(ItemCart.group_id == group_id)
        return list(self._session.execute(stmt).scalars().all())

    def delete_all_for_group(self, group_id: str) -> None:
        for row in self.get_by_group(group_id):
            self._session.delete(row)
        self._session.commit()

    def update(self, entity: ItemCart) -> ItemCart:
        row = self._session.get(ItemCart, (entity.group_id, entity.swiggy_item_id))
        if row is None:
            raise ValueError(
                f"no ItemCart for {entity.group_id!r}/{entity.swiggy_item_id!r}"
            )
        row.quantity = entity.quantity
        row.requested_by = entity.requested_by
        self._session.commit()
        return row

    def delete(self, id: str) -> None:
        group_id, swiggy_item_id = id.split(":", 1)
        row = self._session.get(ItemCart, (group_id, swiggy_item_id))
        if row is not None:
            self._session.delete(row)
            self._session.commit()
