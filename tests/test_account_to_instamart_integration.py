"""Integration check: an AccountDAO-stored token actually drives McpInstamartClient.

M1 (persistence) and M2 (the MCP client) were built in isolation — this proves
the seam between them: the exact plaintext token AccountDAO hands back is what
McpInstamartClient's constructor expects, and using it produces a working
client. HTTP is still mocked (no real network); only the AccountDAO <-> client
wiring is under test here.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from cryptography.fernet import Fernet

from app.accounts.dao import AccountDAO
from app.accounts.models import Account
from app.instamart.mcp_client import McpInstamartClient
from tests.instamart.test_mcp_client import _FakeResponse, _rpc_result, _tool_envelope

HOLDER_PHONE = "+919812345678"


def test_account_dao_token_drives_a_working_mcp_client(session):
    dao = AccountDAO(session, Fernet(Fernet.generate_key()))
    dao.create(
        Account(
            phone=HOLDER_PHONE,
            name="Priya",
            instamart_access_token="real-looking-bearer-token",
        )
    )

    account = dao.get_by_phone(HOLDER_PHONE)
    assert account.instamart_access_token == "real-looking-bearer-token"

    init_ok = _FakeResponse(200, {}, _rpc_result({}))
    cart_ok = _FakeResponse(
        200, {}, _rpc_result(_tool_envelope({"cartId": "c1", "items": []}))
    )
    with patch(
        "app.instamart.mcp_client.urllib.request.urlopen",
        side_effect=[init_ok, init_ok, cart_ok],
    ) as mock_urlopen:
        client = McpInstamartClient(account.instamart_access_token)
        cart = client.get_cart()

    assert cart.cart_id == "c1"
    # The token AccountDAO returned is exactly what went out over the wire.
    sent_request = mock_urlopen.call_args_list[-1].args[0]
    assert (
        sent_request.get_header("Authorization") == "Bearer real-looking-bearer-token"
    )
