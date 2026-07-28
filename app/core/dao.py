"""The common DAO contract every entity DAO implements (CLAUDE.md DRY).

Sync, not async: the codebase is sync end-to-end (FastAPI threadpool `def`
handlers, sync SQLAlchemy) — see CLAUDE.md §2/§4 and the locked concurrency
decision, which overrides the illustrative `async def` shape in CLAUDE.md's
own IDAO snippet.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

T = TypeVar("T")


class IDAO(ABC, Generic[T]):
    @abstractmethod
    def create(self, entity: T) -> T: ...

    @abstractmethod
    def get_by_id(self, id: str) -> T | None: ...

    @abstractmethod
    def update(self, entity: T) -> T: ...

    @abstractmethod
    def delete(self, id: str) -> None: ...
