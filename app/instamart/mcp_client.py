"""`McpInstamartClient` — the real `IInstamartClient`, calling Swiggy's Instamart MCP.

OAuth PKCE flow (obtaining/refreshing the bearer token) is a separate concern
handled at onboarding (M5b) — this class takes an already-obtained token and
makes tool calls with it, matching the proven flow in `scripts/verify_swiggy.py`.

Error handling follows IMPLEMENTATION_PLAN.md §5's policy: auth failures
(401 / JSON-RPC -32001) raise `InstamartAuthError`; a `success:false` envelope
raises `InstamartDomainError` (terminal, surface the message); transient
upstream trouble (502/503/504/timeout) retries with exponential backoff +
jitter (500ms -> 8s cap, max 5 retries) before raising `InstamartUpstreamError`.
"""

from __future__ import annotations

import json
import logging
import random
import secrets
import time
import urllib.error
import urllib.request

from app.instamart.client import (
    IInstamartClient,
    InstamartAuthError,
    InstamartDomainError,
    InstamartUpstreamError,
)
from app.instamart.types import (
    Address,
    Cart,
    CartItemRequest,
    CartLineItem,
    CheckoutResult,
    Order,
    OrderDetails,
    PaymentOption,
    ProductVariation,
)

logger = logging.getLogger(__name__)

MCP_URL = "https://mcp.swiggy.com/im"
PROTOCOL_VERSION = "2025-06-18"

_RETRYABLE_STATUSES = {502, 503, 504}
_MAX_RETRIES = 5
_BASE_DELAY_S = 0.5
_MAX_DELAY_S = 8.0


def _post_with_retry(url: str, body: dict, headers: dict) -> tuple[int, dict, str]:
    last_status, last_headers, last_raw = 0, {}, ""
    for attempt in range(_MAX_RETRIES + 1):
        try:
            data = json.dumps(body).encode()
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            for k, v in headers.items():
                req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, dict(r.headers), r.read().decode()
        except urllib.error.HTTPError as e:
            last_status, last_headers, last_raw = (
                e.code,
                dict(e.headers),
                e.read().decode(),
            )
            if e.code not in _RETRYABLE_STATUSES:
                return last_status, last_headers, last_raw
        except (urllib.error.URLError, TimeoutError) as e:
            last_status, last_headers, last_raw = 0, {}, str(e)
        if attempt < _MAX_RETRIES:
            delay = min(_BASE_DELAY_S * (2**attempt), _MAX_DELAY_S)
            logger.warning(
                "Instamart MCP call failed (attempt %d/%d, status=%s) — retrying in %.1fs",
                attempt + 1,
                _MAX_RETRIES,
                last_status or "unreachable",
                delay,
            )
            time.sleep(delay + random.uniform(0, delay * 0.1))
    logger.error(
        "Instamart MCP unreachable after %d retries: %s", _MAX_RETRIES, last_raw
    )
    raise InstamartUpstreamError(
        f"Instamart MCP unreachable after {_MAX_RETRIES} retries: {last_raw}"
    )


def _parse_envelope(content_type: str, raw: str) -> dict:
    ct = (content_type or "").lower()
    if "text/event-stream" in ct:
        for ln in raw.splitlines():
            ln = ln.strip()
            if ln.startswith("data:"):
                try:
                    obj = json.loads(ln[5:].strip())
                    if isinstance(obj, dict) and ("result" in obj or "error" in obj):
                        return obj
                except json.JSONDecodeError:
                    continue
        logger.warning(
            "No parseable data: line in Instamart SSE response: %r", raw[:500]
        )
        return {}
    try:
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        logger.warning("Instamart response body is not valid JSON: %r", raw[:500])
        return {}


def _error_text(result: dict) -> str:
    try:
        return result["content"][0]["text"]
    except (KeyError, IndexError, TypeError):
        logger.warning("Instamart error result had an unexpected shape: %r", result)
        return "Instamart declined the request"


def _extract_data(result: dict) -> dict:
    structured = result.get("structuredContent")
    if structured:
        return structured
    try:
        text = result["content"][0]["text"]
        return json.loads(text)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        logger.warning("Instamart success result had an unexpected shape: %r", result)
        return {}


def _parse_amount(value: object) -> float | None:
    """Swiggy returns money as display strings ("₹102", "₹1,020.00"). Anything
    that compares or sums them needs a number, so parse rather than trust."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace("₹", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_cart(data: dict) -> Cart:
    # Field names verified against a live cart: per-item price is
    # `discountedFinalPrice` (falling back to `mrp`) — there is no `price` key.
    items = [
        CartLineItem(
            spin_id=it.get("spinId") or "",
            name=it.get("itemName") or "",
            quantity=it.get("quantity", 0),
            price=_parse_amount(it.get("discountedFinalPrice") or it.get("mrp")),
        )
        for it in data.get("items", [])
    ]
    bill = data.get("billBreakdown") or {}
    to_pay = bill.get("toPay")
    if isinstance(to_pay, dict):
        to_pay = to_pay.get("value")
    bill_lines = [
        (line.get("label", ""), line.get("value", ""))
        for line in bill.get("lineItems", [])
        if isinstance(line, dict)
    ]
    return Cart(
        cart_id=data.get("cartId"),
        address_id=data.get("selectedAddress"),
        items=items,
        total=_parse_amount(data.get("cartTotalAmount")),
        to_pay=_parse_amount(to_pay),
        bill_lines=bill_lines,
    )


def _collect_order_ids(data: object) -> list[str]:
    found: set[str] = set()

    def walk(x: object) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                if k.lower() == "orderid" and isinstance(v, (str, int)):
                    found.add(str(v))
                walk(v)
        elif isinstance(x, list):
            for i in x:
                walk(i)

    walk(data)
    return sorted(found)


class McpInstamartClient(IInstamartClient):
    def __init__(self, bearer_token: str) -> None:
        self._bearer_token = bearer_token
        self._session_id: str | None = None
        # Swiggy injects agent guidance (e.g. "STOP, ask the user to pick an
        # address") in each tool response's `message` field (CLAUDE.md: follow
        # these verbatim). Captured here rather than threaded through every
        # return type, since the agent (M5) is the first real consumer and its
        # exact shape isn't decided yet.
        self.last_message: str | None = None

    def get_addresses(self) -> list[Address]:
        data = self._tool("get_addresses", {})
        addresses = data.get("addresses") or []
        return [
            Address(
                id=str(a.get("id") or a.get("addressId") or ""),
                tag=a.get("addressTag")
                or a.get("annotation")
                or a.get("tag")
                or a.get("category")
                or "",
                line=a.get("addressLine")
                or a.get("address")
                or a.get("area")
                or a.get("flatNo")
                or "",
            )
            for a in addresses
            if isinstance(a, dict)
        ]

    def search_products(self, address_id: str, query: str) -> list[ProductVariation]:
        data = self._tool("search_products", {"addressId": address_id, "query": query})
        out: list[ProductVariation] = []
        for product in data.get("products", []):
            product_name = product.get("displayName") or product.get("name") or ""
            for v in product.get("variations", []):
                spin_id = v.get("spinId")
                if not spin_id:
                    continue
                # Verified live: the size lives in `quantityDescription`
                # ("500 ml", "500 ml x 4"). Without it every variation of a
                # product renders identically and differs only by price.
                size = v.get("quantityDescription") or ""
                name = v.get("displayName") or product_name
                price_block = v.get("price") if isinstance(v.get("price"), dict) else {}
                price = price_block.get("offerPrice") or price_block.get("mrp")
                out.append(
                    ProductVariation(
                        spin_id=spin_id,
                        label=f"{name} {size}".strip(),
                        price=price,
                        available=v.get("isInStockAndAvailable", True),
                    )
                )
        return out

    def update_cart(self, address_id: str, items: list[CartItemRequest]) -> Cart:
        data = self._tool(
            "update_cart",
            {
                "selectedAddressId": address_id,
                "items": [{"spinId": i.spin_id, "quantity": i.quantity} for i in items],
            },
        )
        return _parse_cart(data)

    def get_cart(self) -> Cart:
        return _parse_cart(self._tool("get_cart", {}))

    def clear_cart(self) -> None:
        self._tool("clear_cart", {})

    def get_payment_options(self) -> list[PaymentOption]:
        data = self._tool("get_payment_options", {})
        options: list[PaymentOption] = []

        # Group names ("UPI") are what checkout accepts; the entries inside a
        # group are per-app deeplinks and are not payment methods.
        seen = set()
        for group in data.get("allMethods", []):
            name = group.get("groupName")
            if name and name not in seen:
                seen.add(name)
                options.append(PaymentOption(id=name, label=name))

        cod = data.get("cod") or {}
        if cod.get("available"):
            options.append(
                PaymentOption(
                    id=cod.get("id", "COD"),
                    label=cod.get("displayName", "Pay on delivery"),
                )
            )
        return options

    def checkout(
        self, address_id: str, payment_method: str | None = None
    ) -> CheckoutResult:
        args = {"addressId": address_id}
        if payment_method:
            args["paymentMethod"] = payment_method
        data = self._tool("checkout", args)
        return CheckoutResult(
            bridge_url=data.get("bridgeUrl"),
            upi_intent_url=data.get("upiIntentUrl"),
            paas_id=data.get("paasId"),
            order_id=data.get("orderId"),
            status=data.get("status"),
        )

    def get_orders(self) -> list[OrderDetails]:
        """Newest first. Carries items, bill and status, so there is no need
        for `get_order_details` — which is beta-gated and refuses for us."""
        data = self._tool("get_orders", {})
        out: list[OrderDetails] = []
        for o in data.get("orders", []):
            if not isinstance(o, dict) or not o.get("orderId"):
                continue
            bill = o.get("billDetails") or {}
            out.append(
                OrderDetails(
                    order_id=str(o["orderId"]),
                    status=o.get("currentStatus") or o.get("historyStatus") or "",
                    payment_status=o.get("paymentStatus") or "",
                    items=[
                        f"{i.get('name')} x{i.get('quantity')}"
                        for i in o.get("items", [])
                        if isinstance(i, dict)
                    ],
                    total=_parse_amount(bill.get("grandTotal")),
                )
            )
        return out

    def _ensure_session(self) -> None:
        if self._session_id is not None:
            return
        self._call(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "humaracart", "version": "0.1"},
            },
        )
        self._call("notifications/initialized", None, notify=True)

    def _tool(self, name: str, args: dict) -> dict:
        self._ensure_session()
        result = self._call("tools/call", {"name": name, "arguments": args})
        if result.get("isError"):
            # Swiggy signals refusals this way (e.g. get_order_details is
            # beta-gated). Without this the caller gets an empty dict and no
            # idea anything went wrong.
            message = _error_text(result)
            logger.warning("Instamart tool %r refused: %s", name, message)
            raise InstamartDomainError(message)
        data = _extract_data(result)
        if data.get("success") is False:
            message = (data.get("error") or {}).get(
                "message", "Instamart request failed"
            )
            self.last_message = message
            logger.warning("Instamart tool %r failed: %s", name, message)
            raise InstamartDomainError(message)
        self.last_message = data.get("message")
        return data.get("data", data)

    def _call(
        self, method: str, params: dict | None = None, notify: bool = False
    ) -> dict:
        body: dict = {"jsonrpc": "2.0", "method": method}
        if not notify:
            body["id"] = secrets.randbelow(10_000) + 1
        if params is not None:
            body["params"] = params
        headers = {
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self._bearer_token}",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
            headers["MCP-Protocol-Version"] = PROTOCOL_VERSION

        status, resp_headers, raw = _post_with_retry(MCP_URL, body, headers)
        if status == 401:
            logger.warning(
                "Instamart returned 401 for method %r — token likely expired", method
            )
            raise InstamartAuthError(
                "Instamart session expired or invalid — re-authenticate"
            )

        new_sid = resp_headers.get("Mcp-Session-Id") or resp_headers.get(
            "mcp-session-id"
        )
        if new_sid:
            self._session_id = new_sid
        if notify:
            return {}

        content_type = (
            resp_headers.get("Content-Type") or resp_headers.get("content-type") or ""
        )
        parsed = _parse_envelope(content_type, raw)
        if "error" in parsed:
            code = parsed["error"].get("code")
            message = parsed["error"].get("message", "Instamart MCP error")
            if code == -32001:
                logger.warning(
                    "Instamart JSON-RPC auth error for method %r: %s", method, message
                )
                raise InstamartAuthError(message)
            logger.warning(
                "Instamart JSON-RPC error for method %r (code=%s): %s",
                method,
                code,
                message,
            )
            raise InstamartDomainError(message)
        return parsed.get("result", {})
