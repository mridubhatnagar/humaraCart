"""Shared pytest fixtures for the DAO test suite."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import create_all, make_engine


@pytest.fixture
def session() -> Session:
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return sessionmaker(bind=engine)()
