"""PKCE OAuth mechanics for linking a holder's Instamart account.

Deferred at M2 (no consuming route existed yet); built now that onboarding
(M4) is the real consumer. The browser-interactive parts (opening a browser,
running a local redirect-catcher) stay script-only (scripts/verify_swiggy.py,
scripts/verify_mcp_client.py) — in production the "browser redirect" is the
holder's own browser hitting our real `/oauth/callback` route, not a server
we spin up ourselves.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

BASE = "https://mcp.swiggy.com"
SCOPE = "mcp:tools"
CLIENT_ID = "swiggy-mcp"
RESOURCE = "https://mcp.swiggy.com/im"


def generate_pkce_pair() -> tuple[str, str]:
    """Returns (verifier, challenge). The verifier must stay server-side —
    never put it in a URL/redirect param, which would defeat PKCE's actual
    protection against authorization-code interception."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def build_authorize_url(challenge: str, state: str, redirect_uri: str) -> str:
    return f"{BASE}/auth/authorize?" + urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "scope": SCOPE,
            "resource": RESOURCE,
        }
    )


def exchange_code_for_token(code: str, verifier: str, redirect_uri: str) -> str:
    """Returns the access_token. Raises RuntimeError on failure.

    `refresh_token` is confirmed never issued (see DB_DESIGN.md) — only the
    access_token is used.
    """
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
        "client_id": CLIENT_ID,
        "resource": RESOURCE,
    }
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{BASE}/auth/token", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
    tok = json.loads(raw)
    if "access_token" not in tok:
        logger.error("Instamart OAuth token exchange failed: %s", tok)
        raise RuntimeError(f"Instamart token exchange failed: {tok}")
    return tok["access_token"]
