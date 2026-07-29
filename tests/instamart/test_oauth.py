"""OAuth PKCE mechanics: pure functions tested without network; exchange mocked."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.instamart.oauth import (
    build_authorize_url,
    exchange_code_for_token,
    generate_pkce_pair,
)


def test_pkce_pair_challenge_derived_from_verifier():
    verifier, challenge = generate_pkce_pair()
    assert verifier != challenge
    assert len(verifier) > 20
    assert len(challenge) > 20


def test_pkce_pairs_are_unique_per_call():
    v1, c1 = generate_pkce_pair()
    v2, c2 = generate_pkce_pair()
    assert v1 != v2
    assert c1 != c2


def test_build_authorize_url_includes_required_params():
    url = build_authorize_url("chal123", "state123", "https://example.test/callback")
    assert "code_challenge=chal123" in url
    assert "state=state123" in url
    assert "client_id=swiggy-mcp" in url
    assert "redirect_uri=https" in url


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._body


def test_exchange_code_for_token_returns_access_token():
    with patch(
        "app.instamart.oauth.urllib.request.urlopen",
        return_value=_FakeResponse({"access_token": "tok-abc"}),
    ):
        token = exchange_code_for_token(
            "code", "verifier", "https://example.test/callback"
        )
    assert token == "tok-abc"


def test_exchange_code_for_token_raises_on_failure():
    with patch(
        "app.instamart.oauth.urllib.request.urlopen",
        return_value=_FakeResponse({"error": "invalid_grant"}),
    ):
        with pytest.raises(RuntimeError):
            exchange_code_for_token(
                "bad-code", "verifier", "https://example.test/callback"
            )
