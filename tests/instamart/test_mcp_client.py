"""McpInstamartClient tests: JSON-RPC envelope parsing, error classification, retry/backoff.

No real network — `urllib.request.urlopen` is mocked throughout.
"""

from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from app.instamart.client import (
    InstamartAuthError,
    InstamartDomainError,
    InstamartUpstreamError,
)
from app.instamart.mcp_client import McpInstamartClient
from app.instamart.types import Address


class _FakeResponse:
    def __init__(self, status: int, headers: dict, body: str):
        self.status = status
        self.headers = headers
        self._body = body.encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _rpc_result(payload: dict) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": 1, "result": payload})


def _tool_envelope(data: dict, success: bool = True) -> dict:
    """The result shape a tools/call response has once unwrapped from content[0].text."""
    inner = (
        {"success": success, "data": data}
        if success
        else {"success": False, "error": data}
    )
    return {"content": [{"type": "text", "text": json.dumps(inner)}]}


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="x", code=code, msg="err", hdrs={}, fp=io.BytesIO(b"{}")
    )


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch("app.instamart.mcp_client.time.sleep"):
        yield


def test_get_addresses_parses_structured_content():
    init_ok = _FakeResponse(200, {}, _rpc_result({}))
    addresses_ok = _FakeResponse(
        200,
        {},
        _rpc_result(
            {
                "structuredContent": {
                    "addresses": [
                        {"id": "a1", "addressTag": "Home", "addressLine": "221B"}
                    ]
                }
            }
        ),
    )
    with patch(
        "app.instamart.mcp_client.urllib.request.urlopen",
        side_effect=[init_ok, init_ok, addresses_ok],
    ):
        client = McpInstamartClient("tok")
        addresses = client.get_addresses()
    assert addresses == [Address(id="a1", tag="Home", line="221B")]


def test_search_labels_use_the_real_size_field():
    """Field names captured from a live Swiggy response. Variations of one
    product differ only by `quantityDescription` — miss it and every option
    renders identically, leaving price as the only distinguisher."""
    init_ok = _FakeResponse(200, {}, _rpc_result({}))
    search_ok = _FakeResponse(
        200,
        {},
        _rpc_result(
            _tool_envelope(
                {
                    "products": [
                        {
                            "displayName": "Amul Gold Pasteurised Full Cream Milk",
                            "variations": [
                                {
                                    "spinId": "W899J8TO1Z",
                                    "displayName": "Amul Gold Pasteurised Full Cream Milk",
                                    "quantityDescription": "500 ml x 4",
                                    "price": {"mrp": 135, "offerPrice": 131},
                                    "isInStockAndAvailable": True,
                                },
                                {
                                    "spinId": "TYF3262KU8",
                                    "displayName": "Amul Gold Pasteurised Full Cream Milk",
                                    "quantityDescription": "500 ml",
                                    "price": {"mrp": 33, "offerPrice": 32},
                                    "isInStockAndAvailable": True,
                                },
                            ],
                        }
                    ]
                }
            )
        ),
    )
    with patch(
        "app.instamart.mcp_client.urllib.request.urlopen",
        side_effect=[init_ok, init_ok, search_ok],
    ):
        client = McpInstamartClient("tok")
        variations = client.search_products("addr_1", "milk")

    labels = [v.label for v in variations]
    assert labels == [
        "Amul Gold Pasteurised Full Cream Milk 500 ml x 4",
        "Amul Gold Pasteurised Full Cream Milk 500 ml",
    ]
    assert len(set(labels)) == 2  # the whole point: they must be distinguishable
    assert [v.price for v in variations] == [131, 32]


def test_cart_parsing_uses_the_real_price_and_amount_fields():
    """Shapes captured from a live cart. Items carry `discountedFinalPrice`,
    not `price`, and money arrives as display strings ("Rs102") that must be
    parsed — otherwise totals are zero and the checkout cap comparison throws."""
    init_ok = _FakeResponse(200, {}, _rpc_result({}))
    cart_ok = _FakeResponse(
        200,
        {},
        _rpc_result(
            _tool_envelope(
                {
                    "cartId": "c1",
                    "selectedAddress": "246301911",
                    "cartTotalAmount": "₹102",
                    "items": [
                        {
                            "spinId": "ADAPHQI84A",
                            "itemName": "Amul Masti Dahi 380 g",
                            "quantity": 1,
                            "mrp": 35,
                            "discountedFinalPrice": 35,
                        }
                    ],
                    "billBreakdown": {
                        "lineItems": [
                            {"label": "Item Total", "value": "₹35.00"},
                            {"label": "Handling Fee", "value": "₹8.00"},
                        ],
                        "toPay": {"label": "To Pay", "value": "₹102"},
                    },
                }
            )
        ),
    )
    with patch(
        "app.instamart.mcp_client.urllib.request.urlopen",
        side_effect=[init_ok, init_ok, cart_ok],
    ):
        cart = McpInstamartClient("tok").get_cart()

    assert cart.items[0].price == 35
    assert cart.items[0].name == "Amul Masti Dahi 380 g"
    assert cart.to_pay == 102.0
    assert cart.total == 102.0
    assert cart.to_pay >= 100  # numeric, so the checkout cap check cannot throw
    assert cart.bill_lines[0] == ("Item Total", "₹35.00")


def test_auth_error_raised_on_401():
    with patch(
        "app.instamart.mcp_client.urllib.request.urlopen", side_effect=_http_error(401)
    ):
        client = McpInstamartClient("tok")
        with pytest.raises(InstamartAuthError):
            client.get_addresses()


def test_domain_error_raised_on_success_false():
    init_ok = _FakeResponse(200, {}, _rpc_result({}))
    domain_fail = _FakeResponse(
        200,
        {},
        _rpc_result(_tool_envelope({"message": "MIN_ORDER_NOT_MET"}, success=False)),
    )
    with patch(
        "app.instamart.mcp_client.urllib.request.urlopen",
        side_effect=[init_ok, init_ok, domain_fail],
    ):
        client = McpInstamartClient("tok")
        with pytest.raises(InstamartDomainError, match="MIN_ORDER_NOT_MET"):
            client.get_cart()


def test_retries_transient_upstream_error_then_succeeds():
    init_ok = _FakeResponse(200, {}, _rpc_result({}))
    cart_ok = _FakeResponse(
        200, {}, _rpc_result(_tool_envelope({"cartId": "c1", "items": []}))
    )
    with patch(
        "app.instamart.mcp_client.urllib.request.urlopen",
        side_effect=[init_ok, init_ok, _http_error(502), cart_ok],
    ):
        client = McpInstamartClient("tok")
        cart = client.get_cart()
    assert cart.cart_id == "c1"


def test_upstream_error_after_exhausting_retries():
    init_ok = _FakeResponse(200, {}, _rpc_result({}))
    with patch(
        "app.instamart.mcp_client.urllib.request.urlopen",
        side_effect=[init_ok, init_ok] + [_http_error(503)] * 6,
    ):
        client = McpInstamartClient("tok")
        with pytest.raises(InstamartUpstreamError):
            client.get_cart()


def test_captures_agent_guidance_message_on_success():
    """Swiggy's STOP-and-ask instructions ride in `message` — must not be dropped."""
    init_ok = _FakeResponse(200, {}, _rpc_result({}))
    addresses_with_message = _FakeResponse(
        200,
        {},
        _rpc_result(
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "success": True,
                                "data": {"addresses": []},
                                "message": "STOP. Ask the user to pick an address before proceeding.",
                            }
                        ),
                    }
                ]
            }
        ),
    )
    with patch(
        "app.instamart.mcp_client.urllib.request.urlopen",
        side_effect=[init_ok, init_ok, addresses_with_message],
    ):
        client = McpInstamartClient("tok")
        client.get_addresses()
    assert (
        client.last_message
        == "STOP. Ask the user to pick an address before proceeding."
    )


def test_captures_message_even_on_domain_error():
    init_ok = _FakeResponse(200, {}, _rpc_result({}))
    domain_fail = _FakeResponse(
        200,
        {},
        _rpc_result(_tool_envelope({"message": "MIN_ORDER_NOT_MET"}, success=False)),
    )
    with patch(
        "app.instamart.mcp_client.urllib.request.urlopen",
        side_effect=[init_ok, init_ok, domain_fail],
    ):
        client = McpInstamartClient("tok")
        with pytest.raises(InstamartDomainError):
            client.get_cart()
    assert client.last_message == "MIN_ORDER_NOT_MET"


def test_checkout_returns_bridge_url_unmodified():
    init_ok = _FakeResponse(200, {}, _rpc_result({}))
    checkout_ok = _FakeResponse(
        200,
        {},
        _rpc_result(
            _tool_envelope(
                {
                    "bridgeUrl": "https://pay.example/very/long/real/url",
                    "upiIntentUrl": "upi://pay?x=1",
                    "paasId": "p1",
                    "orderId": "o1",
                    "status": "PENDING_PAYMENT",
                }
            )
        ),
    )
    with patch(
        "app.instamart.mcp_client.urllib.request.urlopen",
        side_effect=[init_ok, init_ok, checkout_ok],
    ):
        client = McpInstamartClient("tok")
        result = client.checkout("addr_1", payment_method="UPI")
    assert result.bridge_url == "https://pay.example/very/long/real/url"
    assert result.status == "PENDING_PAYMENT"
