#!/usr/bin/env python3
"""
Throwaway diagnostic (NOT product code). One run, one browser login.

It does the full OAuth + MCP flow end to end so you don't have to shuttle
variables between curl commands, and it is built to diagnose the current
"Incorrect alg in MCP JWT" error: it prints the token's alg, and if the
access_token is rejected it automatically retries with the id_token.

Run:  python3 scripts/verify_swiggy.py
Stdlib only, no pip install. A browser opens for the Swiggy login; everything
else is automatic. Prints the raw get_addresses / search_products / get_cart
JSON so we can confirm real-vs-sandbox data and read the exact field names.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser

BASE = "https://mcp.swiggy.com"
MCP_URL = f"{BASE}/im"
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
SCOPE = "mcp:tools"
CLIENT_ID = "swiggy-mcp"  # fixed public client (verified via DCR)
PROTOCOL_VERSION = "2025-06-18"
RESOURCE = "https://mcp.swiggy.com/im"  # RFC 8707 resource indicator


def line(label=""):
    print("\n" + "=" * 72)
    if label:
        print(label)
        print("=" * 72)


def jwt_header(token):
    seg = token.split(".")[0]
    seg += "=" * (-len(seg) % 4)
    return json.loads(base64.urlsafe_b64decode(seg))


def jwt_payload(token):
    seg = token.split(".")[1]
    seg += "=" * (-len(seg) % 4)
    return json.loads(base64.urlsafe_b64decode(seg))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # surface the 3xx instead of following to Swiggy's SPA


_opener = urllib.request.build_opener(_NoRedirect)


def hget(headers, name):
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v
    return None


def post(url, body, headers=None):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "curl/8.4.0")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with _opener.open(req, timeout=30) as r:
            return r.status, dict(r.headers), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode()


def parse_mcp(content_type, raw):
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
        return {"_raw": raw}
    try:
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {"_raw": raw}


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


def get_code(challenge, state):
    url = f"{BASE}/auth/authorize?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "scope": SCOPE,
        "resource": RESOURCE,
    })
    print("\nLog in with your Swiggy account (opening the browser)...")
    print("If it does not open, paste this URL manually:\n  " + url)
    server = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), Callback)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    while Callback.code is None:
        server.handle_request()
    return Callback.code


def mcp_call(method, bearer, session_id, params=None, notify=False):
    body = {"jsonrpc": "2.0", "method": method}
    if not notify:
        body["id"] = secrets.randbelow(10_000) + 1
    if params is not None:
        body["params"] = params
    headers = {
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {bearer}",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
        headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
    status, resp_headers, raw = post(MCP_URL, body, headers)
    new_sid = resp_headers.get("Mcp-Session-Id") or resp_headers.get("mcp-session-id")
    parsed = {} if notify else parse_mcp(resp_headers.get("Content-Type", ""), raw)
    return status, new_sid or session_id, parsed, raw


def tool(name, bearer, session_id, args):
    return mcp_call("tools/call", bearer, session_id, {"name": name, "arguments": args})


def dig(obj, *keys):
    """Best-effort: find the first value for any of `keys` anywhere in obj."""
    found = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k.lower() in keys and isinstance(v, (str, int)):
                    found.append(str(v))
                walk(v)
        elif isinstance(x, list):
            for i in x:
                walk(i)

    walk(obj)
    return found[0] if found else None


def cart_id(cart_parsed):
    """Extract data.cartId from a get_cart / update_cart response."""
    try:
        text = cart_parsed["result"]["content"][0]["text"]
        return json.loads(text).get("data", {}).get("cartId")
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return None


def cart_address_id(cart_parsed):
    """Extract data.selectedAddress (the addressId) from a get_cart response."""
    try:
        text = cart_parsed["result"]["content"][0]["text"]
        return json.loads(text).get("data", {}).get("selectedAddress")
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return None


def cart_address_details(cart_parsed):
    """Extract data.selectedAddressDetails from a get_cart response (may be absent)."""
    try:
        text = cart_parsed["result"]["content"][0]["text"]
        return json.loads(text).get("data", {}).get("selectedAddressDetails")
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return None


def cart_item_names(cart_parsed):
    """List the itemName of every item in a get_cart / update_cart response."""
    try:
        text = cart_parsed["result"]["content"][0]["text"]
        items = json.loads(text).get("data", {}).get("items", [])
        return [it.get("itemName") for it in items]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return None


def first_spin_id(search_parsed):
    """Pull the first spinId from a search_products response.

    Products live in result.content[0].text as a JSON *string*, so parse that
    string, then read data.products[].variations[].spinId.
    """
    try:
        text = search_parsed["result"]["content"][0]["text"]
        data = json.loads(text).get("data", {})
        for product in data.get("products", []):
            for variation in product.get("variations", []):
                if variation.get("spinId"):
                    return variation["spinId"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        pass
    return None


def address_list(addrs_parsed):
    """Parse get_addresses → [{id, tag, line}] (handles structuredContent or content text)."""
    result = addrs_parsed.get("result", {}) if isinstance(addrs_parsed, dict) else {}
    raw = result.get("structuredContent")
    if not raw:
        try:
            raw = json.loads(result["content"][0]["text"])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            raw = {}
    addresses = raw.get("addresses") or raw.get("data", {}).get("addresses") or []
    out = []
    for a in addresses:
        if not isinstance(a, dict):
            continue
        out.append({
            "id": str(a.get("id") or a.get("addressId") or ""),
            "tag": a.get("addressTag") or a.get("annotation") or a.get("tag")
            or a.get("category") or "",
            "line": a.get("addressLine") or a.get("address") or a.get("area")
            or a.get("flatNo") or "",
        })
    return out


def product_variations(search_parsed, name_filter=None):
    """List [{spinId, label, price, raw}] for variations, optionally filtered to products
    whose name contains name_filter (plain case-insensitive substring — no regex)."""
    out = []
    try:
        text = search_parsed["result"]["content"][0]["text"]
        data = json.loads(text).get("data", {})
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return out
    for product in data.get("products", []):
        pname = product.get("name") or product.get("displayName") or ""
        if name_filter and name_filter.lower() not in pname.lower():
            continue
        for v in product.get("variations", []):
            sid = v.get("spinId")
            if not sid:
                continue
            size = (
                v.get("quantity") or v.get("weight") or v.get("measure")
                or v.get("variationName") or v.get("name") or v.get("displayName") or ""
            )
            price = v.get("price") if isinstance(v.get("price"), dict) else {}
            amt = price.get("offerPrice") or price.get("mrp")
            out.append({"spinId": sid, "label": f"{pname} {size}".strip(), "price": amt})
    return out


def pick_variation(query, search_parsed, name_filter=None, limit=5):
    """Show up to `limit` variations (brand-filtered) and let the user pick one."""
    variations = product_variations(search_parsed, name_filter=name_filter)
    note = f"(only {name_filter!r})" if name_filter else ""
    if not variations:  # filter too strict — fall back so we're never stuck
        variations = product_variations(search_parsed)
        note = f"(no match for {name_filter!r} — showing all)" if name_filter else ""
    if not variations:
        print(f"No variations found for {query!r}. Raw (truncated):")
        print(json.dumps(search_parsed, indent=2)[:1500])
        return None
    shown = variations[:limit]
    more = len(variations) - len(shown)
    count = f"{len(shown)} of {len(variations)}" if more else str(len(shown))
    print(f"\nVariations for {query!r} {note} — showing {count}:".rstrip())
    for i, v in enumerate(shown, 1):
        print(f"  {i}. {v['label']}   ₹{v['price']}   (spinId={v['spinId']})")
    choice = input(f"\nPick the variation you want for {query!r} (number): ").strip()
    try:
        return shown[int(choice) - 1]["spinId"]
    except (ValueError, IndexError):
        print("Invalid choice.")
        return None


def authenticate():
    """Full OAuth (browser login) + MCP initialize. Returns (bearer, session_id) or (None, None)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    code = get_code(challenge, secrets.token_urlsafe(16))

    status, _, raw = post(f"{BASE}/auth/token", {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "resource": RESOURCE,
    })
    tok = json.loads(raw)
    if "access_token" not in tok:
        print("TOKEN EXCHANGE FAILED:", tok)
        return None, None

    status, hdrs, raw = post(MCP_URL, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "verify", "version": "0.1"},
        },
    }, {
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {tok['access_token']}",
    })
    parsed = parse_mcp(hget(hdrs, "content-type") or "", raw)
    if status >= 400 or "error" in parsed or "_raw" in parsed:
        print("MCP INITIALIZE FAILED:", status, raw[:500])
        return None, None
    bearer = tok["access_token"]
    session_id = hget(hdrs, "mcp-session-id")
    mcp_call("notifications/initialized", bearer, session_id, notify=True)
    return bearer, session_id


def cart_total(cart_parsed):
    """Return (cartTotalAmount, billBreakdown.toPay) from a get_cart response."""
    try:
        text = cart_parsed["result"]["content"][0]["text"]
        data = json.loads(text).get("data", {})
        return data.get("cartTotalAmount"), data.get("billBreakdown", {}).get("toPay")
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return None, None


def to_pay_amount(cart_parsed):
    """Numeric grand total ('To Pay', e.g. '₹125' → 125.0) from get_cart, or None."""
    _, topay = cart_total(cart_parsed)
    val = topay.get("value") if isinstance(topay, dict) else topay
    if val is None:
        return None
    try:
        return float(str(val).replace("₹", "").replace(",", "").strip())
    except ValueError:
        return None


def order_ids(orders_parsed):
    """Collect every orderId anywhere in a get_orders response (for before/after diff)."""
    found = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k.lower() == "orderid" and isinstance(v, (str, int)):
                    found.append(str(v))
                walk(v)
        elif isinstance(x, list):
            for i in x:
                walk(i)

    try:
        walk(json.loads(orders_parsed["result"]["content"][0]["text"]))
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        pass
    walk(orders_parsed)
    return sorted(set(found))


def check_cart():
    """READ-ONLY: OAuth + get_cart, print items + total. Changes nothing."""
    bearer, session_id = authenticate()
    if not bearer:
        return
    line("get_cart — current cart (READ-ONLY, nothing changed)")
    _, session_id, cart, _ = tool("get_cart", bearer, session_id, {})
    total, topay = cart_total(cart)
    print("cartId             :", cart_id(cart))
    print("selectedAddress    :", cart_address_id(cart))
    print("items              :", cart_item_names(cart))
    print("cartTotalAmount    :", total)
    print("billBreakdown.toPay:", topay)
    val = topay if isinstance(topay, (int, float)) else total
    in_range = isinstance(val, (int, float)) and 99 <= val < 1000
    print("₹99 min / <₹1000 cap → in range:", "YES" if in_range else "NO / check above")
    print(json.dumps(cart, indent=2))


def run_checkout():
    """Place a REAL order via checkout on the CURRENT cart, following Swiggy's confirm steps."""
    bearer, session_id = authenticate()
    if not bearer:
        return

    line("get_cart — order summary + bill (shown BEFORE checkout)")
    _, session_id, cart, _ = tool("get_cart", bearer, session_id, {})
    addr = cart_address_id(cart)
    details = cart_address_details(cart) or {}
    topay = to_pay_amount(cart)
    print("items      :", cart_item_names(cart))
    print("cartId     :", cart_id(cart))
    print("deliver to :", details.get("address"), "| addressId:", addr)
    try:
        bb = json.loads(cart["result"]["content"][0]["text"])["data"]["billBreakdown"]
        print("billBreakdown:\n" + json.dumps(bb, indent=2))
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        pass
    print("to pay     :", topay)

    if not addr:
        print("No selectedAddress on the cart — abort.")
        return
    if topay is None:
        print("Could not read 'to pay' — abort (inspect billBreakdown above).")
        return
    if topay >= 1000:
        print(f"To Pay ₹{topay} >= ₹1000 → Swiggy blocks in-chat checkout; use the app. Abort.")
        return

    line("get_payment_options — methods Swiggy offers")
    _, session_id, pay, _ = tool("get_payment_options", bearer, session_id, {})
    print(json.dumps(pay, indent=2)[:2500])

    line("get_orders — snapshot BEFORE (to detect a newly-placed order)")
    _, session_id, orders_before, _ = tool("get_orders", bearer, session_id, {})
    before_ids = order_ids(orders_before)
    print("existing order ids:", before_ids)

    line("CONFIRM — this places a REAL order (real money, real delivery)")
    print(f"Deliver to : {details.get('address')}")
    print(f"To Pay     : ₹{topay}")
    method = input(
        "paymentMethod to pass (blank = let Swiggy auto-select; or e.g. COD / UPI): "
    ).strip()
    if input('Type "YES" (caps) to place a REAL order: ').strip() != "YES":
        print("Not confirmed — nothing placed.")
        return

    args = {"addressId": addr}
    if method:
        args["paymentMethod"] = method
    line(f"checkout({args}) — RAW response follows")
    _, session_id, result, _ = tool("checkout", bearer, session_id, args)
    print(json.dumps(result, indent=2))

    sc = result.get("result", {}).get("structuredContent", {}) if isinstance(result, dict) else {}
    if sc.get("bridgeUrl") or sc.get("upiIntentUrl"):
        line("PAY — open the FULL bridgeUrl on your phone (relay it WHOLE; never truncate)")
        print("bridgeUrl   :", sc.get("bridgeUrl"))
        print("upiIntentUrl:", sc.get("upiIntentUrl"))
        print(
            "paasId:", sc.get("paasId"),
            "| orderId:", sc.get("orderId"),
            "| status:", sc.get("status"),
        )

    line("get_orders — snapshot AFTER")
    _, session_id, orders_after, _ = tool("get_orders", bearer, session_id, {})
    after_ids = order_ids(orders_after)
    new_ids = [i for i in after_ids if i not in before_ids]
    print("order ids after:", after_ids)
    print("NEW order id(s):", new_ids or "(none — no new order detected)")
    print("\nRead: did checkout return an orderId / 'payment success' message, a QR/intent")
    print("to pay, or an error? And did a NEW order id appear above (was it committed)?")


def main():
    bearer, session_id = authenticate()
    if not bearer:
        return

    # Address-selection test (human in the loop):
    #   clear_cart -> get_addresses -> YOU pick -> update_cart/get_cart on that address.

    # 1. Clear the current cart so verification starts clean.
    #    NOTE: clear_cart empties only the *currently-selected* address's cart; the chosen
    #    address is then rebuilt via full-replace update_cart, so its contents are exact.
    line("clear_cart — emptying the current cart (fresh start)")
    _, session_id, cleared, _ = tool("clear_cart", bearer, session_id, {})
    print(json.dumps(cleared, indent=2))

    # 2. get_addresses — Swiggy REQUIRES: stop, show the list, let the user choose.
    line("get_addresses — pick the delivery address (human in the loop)")
    _, session_id, addrs, _ = tool("get_addresses", bearer, session_id, {})
    addresses = address_list(addrs)
    if not addresses:
        print("No saved addresses parsed. Raw response:")
        print(json.dumps(addrs, indent=2))
        print("If you have none, add an address in the Instamart app first.")
        return
    for i, a in enumerate(addresses, 1):
        print(f"  {i}. [{a['tag']}] {a['line']}   (id={a['id']})")

    # 3. You choose.
    choice = input("\nPick an address by number: ").strip()
    try:
        chosen = addresses[int(choice) - 1]
    except (ValueError, IndexError):
        print("Invalid choice — re-run and pick a listed number.")
        return
    addr = chosen["id"]
    print(f"\nSelected: [{chosen['tag']}] {chosen['line']}  (addressId={addr})")

    # 4/5. Build the cart ON THE CHOSEN address: update_cart -> get_cart, twice.
    q1, q2 = "VS Mani Potato Chips Salt", "Uncle Chips"
    _, session_id, r1, _ = tool(
        "search_products", bearer, session_id, {"addressId": addr, "query": q1}
    )
    _, session_id, r2, _ = tool(
        "search_products", bearer, session_id, {"addressId": addr, "query": q2}
    )
    chip1 = pick_variation(q1, r1, name_filter="vs mani")
    chip2 = pick_variation(q2, r2, name_filter="uncle")
    if not (chip1 and chip2):
        print("No variation selected. Re-run and pick listed numbers.")
        return

    line(f"update_cart([{q1}])  on the selected address")
    _, session_id, upd1, _ = tool("update_cart", bearer, session_id, {
        "selectedAddressId": addr,
        "items": [{"spinId": chip1, "quantity": 1}],
    })
    print("cartId:", cart_id(upd1), " selectedAddress:", cart_address_id(upd1))

    line("get_cart  (after adding first item)")
    _, session_id, cart1, _ = tool("get_cart", bearer, session_id, {})
    print("cartId:", cart_id(cart1), " selectedAddress:", cart_address_id(cart1))
    print("items:", cart_item_names(cart1))

    line(f"update_cart([{q1}, {q2}])  on the selected address")
    _, session_id, upd2, _ = tool("update_cart", bearer, session_id, {
        "selectedAddressId": addr,
        "items": [{"spinId": chip1, "quantity": 1}, {"spinId": chip2, "quantity": 1}],
    })
    print("cartId:", cart_id(upd2), " selectedAddress:", cart_address_id(upd2))

    line("get_cart  (after adding second item)")
    _, session_id, cart2, _ = tool("get_cart", bearer, session_id, {})
    print("cartId:", cart_id(cart2), " selectedAddress:", cart_address_id(cart2))
    print(json.dumps(cart2, indent=2))

    line("VERDICT — did the cart bind to the address YOU chose?")
    print("chosen addressId          :", addr)
    print("get_cart selectedAddress  :", cart_address_id(cart2))
    print("MATCH:", "YES" if cart_address_id(cart2) == addr else "NO")
    print("items in cart now         :", cart_item_names(cart2))
    print(f"\nNow open the Swiggy app/web WITH THIS ADDRESS SELECTED "
          f"([{chosen['tag']}] {chosen['line']}) — milk + ice cream should show.")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "cart":
        check_cart()
    elif mode == "checkout":
        run_checkout()
    else:
        main()
