"""SQLAlchemy engine/session plumbing.

One `Base` shared by every app's ORM model (app/accounts/models.py, etc). The
backend is a connection-URL detail (CLAUDE.md) — SQLite for the demo, Postgres
later via `database_url` alone; nothing else here changes.
"""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str) -> Engine:
    is_sqlite = database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(database_url, connect_args=connect_args)
    if is_sqlite:
        # SQLite ignores FK constraints unless turned on per connection.
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=make_engine(database_url))


def create_all(engine: Engine) -> None:
    """Create every table.

    `Base.metadata` only knows about model classes that have actually been
    imported, so calling `Base.metadata.create_all` directly from a module that
    imported only some of them builds a *partial* schema — and the missing
    table only surfaces later as "no such table". Importing them all here means
    every caller gets the whole schema. Imports are function-local because the
    models import `Base` from this module.
    """
    from app.accounts.models import Account  # noqa: F401
    from app.cart.models import ItemCart  # noqa: F401
    from app.groups.models import Group, GroupAccount  # noqa: F401
    from app.invites.models import InviteToken  # noqa: F401

    Base.metadata.create_all(engine)
