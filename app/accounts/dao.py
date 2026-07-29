"""The `Account` DAO — interface and implementation together (one file per DAO).

`IAccountDAO` is the contract callers (CartService, the agent, `dependencies.py`)
should depend on — `get_by_phone` is a concrete convenience on the interface
itself (pure delegation to `get_by_id`, inherited by any implementation for
free), so a caller typed against the interface still sees the domain-specific
query. `AccountDAO` is the SQLAlchemy-backed implementation; a future
`InMemoryAccountDAO` test double would implement the same `IAccountDAO`
interface.

Encryption is DAO-owned (DB_DESIGN.md): callers pass/receive plaintext tokens;
what lands in SQLite is always ciphertext. The `Fernet` cipher is injected
(constructor DI, CLAUDE.md), not read from settings/env here, so this stays
testable without touching real secrets.

Every method deals in fresh, session-detached `Account` instances holding
plaintext — never the session-attached row (which holds ciphertext) — so a
caller can't accidentally re-persist a plaintext token by mutating what they
were handed.
"""

from __future__ import annotations

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app.accounts.models import Account
from app.core.dao import IDAO


class IAccountDAO(IDAO[Account]):
    def get_by_phone(self, phone: str) -> Account | None:
        return self.get_by_id(phone)


class AccountDAO(IAccountDAO):
    def __init__(self, session: Session, fernet: Fernet) -> None:
        self._session = session
        self._fernet = fernet

    def create(self, entity: Account) -> Account:
        row = Account(
            phone=entity.phone,
            name=entity.name,
            instamart_access_token=self._encrypt(entity.instamart_access_token),
            token_expires_at=entity.token_expires_at,
            instamart_refresh_token=self._encrypt(entity.instamart_refresh_token),
        )
        self._session.add(row)
        self._session.commit()
        return entity

    def get_by_id(self, id: str) -> Account | None:
        row = self._session.get(Account, id)
        if row is None:
            return None
        return Account(
            phone=row.phone,
            name=row.name,
            instamart_access_token=self._decrypt(row.instamart_access_token),
            token_expires_at=row.token_expires_at,
            instamart_refresh_token=self._decrypt(row.instamart_refresh_token),
        )

    def update(self, entity: Account) -> Account:
        row = self._session.get(Account, entity.phone)
        if row is None:
            raise ValueError(f"no Account for phone {entity.phone!r}")
        row.name = entity.name
        row.instamart_access_token = self._encrypt(entity.instamart_access_token)
        row.token_expires_at = entity.token_expires_at
        row.instamart_refresh_token = self._encrypt(entity.instamart_refresh_token)
        self._session.commit()
        return entity

    def delete(self, id: str) -> None:
        row = self._session.get(Account, id)
        if row is not None:
            self._session.delete(row)
            self._session.commit()

    def _encrypt(self, value: str | None) -> str | None:
        return (
            self._fernet.encrypt(value.encode()).decode() if value is not None else None
        )

    def _decrypt(self, value: str | None) -> str | None:
        return (
            self._fernet.decrypt(value.encode()).decode() if value is not None else None
        )
