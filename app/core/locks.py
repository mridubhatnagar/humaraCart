"""`IGroupLock` — mutual exclusion for one household's critical section.

Guards the read-modify-write window spanning an LLM call and Swiggy's
`update_cart` (full-replace, no version/ETag param) — nothing on Swiggy's
side supports optimistic compare-and-swap, so pessimistic exclusion held for
the whole turn is the only option (plan_v2.md §2.1). `PostgresGroupLock` is
correct across processes, not just within one, so it needs no future
migration if the app is ever scaled beyond a single container.

Only `ConversationService` acquires this, for the whole agent turn — every
cart-changing call reaches `CartService` through that turn (see
`app/cart/service.py`'s docstring), so a second acquisition there would just
be the same key from a second DB session nested inside the first: Postgres
advisory locks are per-session, not per-thread, so that would block the
outer session's own lock forever rather than no-op.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker


class IGroupLock(ABC):
    @abstractmethod
    def acquire(self, group_id: str) -> AbstractContextManager[None]: ...


class PostgresGroupLock(IGroupLock):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @contextmanager
    def acquire(self, group_id: str) -> Iterator[None]:
        # hashtext(), not Python's hash(): str hashing is randomized per
        # process (PYTHONHASHSEED), so two workers would compute different
        # keys for the same group_id and never actually exclude each other.
        with self._session_factory() as session:
            session.execute(select(func.pg_advisory_xact_lock(func.hashtext(group_id))))
            try:
                yield
            finally:
                # Ends the transaction, releasing the lock. Nothing is ever
                # written through this session, so rollback vs. commit makes
                # no difference beyond that.
                session.rollback()


class InMemoryGroupLock(IGroupLock):
    """Test double — a per-group `threading.Lock`, no Postgres involved."""

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    @contextmanager
    def acquire(self, group_id: str) -> Iterator[None]:
        with self._locks_guard:
            lock = self._locks.setdefault(group_id, threading.Lock())
        with lock:
            yield
