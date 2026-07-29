#!/usr/bin/env python3
"""
Live verification: M1 (AccountDAO) + M2 (McpInstamartClient) against the REAL
Swiggy MCP — not mocked. Throwaway diagnostic (NOT product code).

The OAuth browser-login dance below is lifted verbatim from the proven
scripts/verify_swiggy.py (stdlib-only, browser-interactive — that part can't
be automated). Unlike that script, the actual Instamart calls go through the
real, production `McpInstamartClient` (app/instamart/mcp_client.py) built in
M2 — this proves that class against live data, not a reimplementation.

Run inside docker (has cryptography/sqlalchemy already; -p publishes the
OAuth callback port so your host browser's redirect can reach it):

  docker compose run --rm -p 8765:8765 test python scripts/verify_mcp_client.py

The authorize URL is printed — open it in your OWN browser (the container
has none) and log in; the redirect back to localhost:8765 is what -p enables.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.instamart.client import (
    InstamartAuthError,
    InstamartDomainError,
    InstamartUpstreamError,
)
from app.instamart.mcp_client import McpInstamartClient

BASE = "https://mcp.swiggy.com"
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
SCOPE = "mcp:tools"
CLIENT_ID = "swiggy-mcp"
RESOURCE = "https://mcp.swiggy.com/im"


def line(label: str = "") -> None:
    print("\n" + "=" * 72)
    if label:
        print(label)
        print("=" * 72)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _post(url: str, body: dict) -> str:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "curl/8.4.0")
    try:
        with _opener.open(req, timeout=30) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        return e.read().decode()


class Callback(http.server.BaseHTTPRequestHandler):
    code = None

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        Callback.code = (q.get("code") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h2>Done. Return to the terminal.</h2>")

    def log_message(self, *_):
        pass


def get_code(challenge: str, state: str) -> str:
    url = f"{BASE}/auth/authorize?" + urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "scope": SCOPE,
            "resource": RESOURCE,
        }
    )
    print("\nOpen this URL in your OWN browser and log in with your Swiggy account:")
    print("  " + url)
    # 0.0.0.0, not 127.0.0.1: inside docker, the host's redirect only reaches
    # this server via the published port if it's listening on all interfaces.
    server = http.server.HTTPServer(("0.0.0.0", REDIRECT_PORT), Callback)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    while Callback.code is None:
        server.handle_request()
    return Callback.code


def get_real_bearer_token() -> str:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    code = get_code(challenge, secrets.token_urlsafe(16))

    raw = _post(
        f"{BASE}/auth/token",
        {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "resource": RESOURCE,
        },
    )
    tok = json.loads(raw)
    if "access_token" not in tok:
        print("TOKEN EXCHANGE FAILED:", tok)
        sys.exit(1)
    print(
        "\nrefresh_token present:", "refresh_token" in tok, "-> keys:", list(tok.keys())
    )
    return tok["access_token"]


def verify_mcp_client(bearer_token: str) -> bool:
    """Returns True only if all three live calls actually succeeded."""
    line("McpInstamartClient.get_addresses() — REAL call")
    client = McpInstamartClient(bearer_token)
    try:
        addresses = client.get_addresses()
    except (InstamartAuthError, InstamartDomainError, InstamartUpstreamError) as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        return False
    if not addresses:
        print("No saved addresses — add one in the Instamart app first. Aborting.")
        return False
    for i, a in enumerate(addresses, 1):
        print(f"  {i}. [{a.tag}] {a.line}  (id={a.id})")
    address_id = addresses[0].id

    line(
        f"McpInstamartClient.search_products(address_id={address_id!r}, 'milk') — REAL call"
    )
    try:
        variations = client.search_products(address_id, "milk")
    except (InstamartAuthError, InstamartDomainError, InstamartUpstreamError) as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        return False
    if not variations:
        print(
            "No variations found for 'milk' — unexpected, but not fatal to this check."
        )
    for v in variations[:5]:
        print(f"  {v.label}  ₹{v.price}  (spinId={v.spin_id}, available={v.available})")

    line("McpInstamartClient.get_cart() — REAL call")
    try:
        cart = client.get_cart()
    except (InstamartAuthError, InstamartDomainError, InstamartUpstreamError) as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        return False
    print(
        "cartId:",
        cart.cart_id,
        "| address:",
        cart.address_id,
        "| items:",
        [i.name for i in cart.items],
    )
    print("total:", cart.total, "| to_pay:", cart.to_pay)
    return True


def verify_account_dao_roundtrip(bearer_token: str) -> bool:
    """Returns True only if the round-trip genuinely ran and passed."""
    from cryptography.fernet import Fernet
    from sqlalchemy.orm import sessionmaker

    from app.accounts.dao import AccountDAO
    from app.accounts.models import Account
    from app.core.db import Base, make_engine

    line("AccountDAO round-trip with the REAL token — encrypt, store, decrypt")
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    dao = AccountDAO(session, Fernet(Fernet.generate_key()))

    dao.create(
        Account(
            phone="+910000000001", name="LiveTest", instamart_access_token=bearer_token
        )
    )
    account = dao.get_by_phone("+910000000001")
    if account.instamart_access_token != bearer_token:
        print("FAILED: AccountDAO did not round-trip the real token!")
        return False
    print("AccountDAO round-trip OK — decrypted token matches the original.")

    line("McpInstamartClient built from the AccountDAO-decrypted token — REAL call")
    client = McpInstamartClient(account.instamart_access_token)
    try:
        addresses = client.get_addresses()
    except (InstamartAuthError, InstamartDomainError, InstamartUpstreamError) as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        return False
    print("Address count via DAO-sourced token:", len(addresses))
    return True


def main() -> None:
    bearer_token = get_real_bearer_token()
    mcp_ok = verify_mcp_client(bearer_token)
    dao_ok = verify_account_dao_roundtrip(bearer_token)

    line("SUMMARY")
    print(
        "McpInstamartClient live calls (addresses/search/cart):",
        "PASSED" if mcp_ok else "FAILED",
    )
    print(
        "AccountDAO round-trip + DAO-sourced client call      :",
        "PASSED" if dao_ok else "FAILED",
    )
    if not (mcp_ok and dao_ok):
        sys.exit(1)


if __name__ == "__main__":
    main()
