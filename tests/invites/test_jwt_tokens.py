"""sign/verify: roundtrip, expiry, tamper detection."""

from __future__ import annotations

from datetime import timedelta

import jwt
import pytest

from app.invites.jwt_tokens import sign, verify

SECRET = "test-secret"


def test_roundtrip():
    token = sign({"group_id": "g1"}, SECRET, timedelta(minutes=10))
    payload = verify(token, SECRET)
    assert payload["group_id"] == "g1"


def test_expired_token_raises():
    token = sign({"group_id": "g1"}, SECRET, timedelta(seconds=-1))
    with pytest.raises(jwt.ExpiredSignatureError):
        verify(token, SECRET)


def test_wrong_secret_raises():
    token = sign({"group_id": "g1"}, SECRET, timedelta(minutes=10))
    with pytest.raises(jwt.InvalidSignatureError):
        verify(token, "wrong-secret")
