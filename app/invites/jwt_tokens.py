"""Generic signed, expiring token helpers — used for both invite links and the
OAuth `state` param. A thin wrapper over PyJWT so callers don't touch the
library directly; no class needed since these are pure functions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt


def sign(payload: dict, secret: str, expires_in: timedelta) -> str:
    to_encode = {**payload, "exp": datetime.now(timezone.utc) + expires_in}
    return jwt.encode(to_encode, secret, algorithm="HS256")


def verify(token: str, secret: str) -> dict:
    """Raises jwt.PyJWTError (or a subclass) if invalid/expired."""
    return jwt.decode(token, secret, algorithms=["HS256"])
