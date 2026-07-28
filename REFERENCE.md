# HumaraCart — Swiggy MCP Reference

Verbatim agent-guidance and doc links for the Swiggy Builders Club Instamart MCP.

> **Sourcing:** quotes are from each tool's verbatim `.md` source (append `.md` to any doc
> URL) or from live tool-response `message` fields. Treat the links as authoritative.
> Two tools — `check_payment_status`, `confirm_order` — are **live-only** (no doc page);
> they're captured here from the live `checkout` response message.

---

## Doc links

- Builders home — https://mcp.swiggy.com/builders/
- Full docs (single-file, searchable) — https://mcp.swiggy.com/builders/llms-full.txt
- Authenticate (OAuth 2.1 PKCE + DCR) — https://mcp.swiggy.com/builders/docs/start/authenticate/
- Errors reference — https://mcp.swiggy.com/builders/docs/reference/errors/
- Instamart reference (index) — https://mcp.swiggy.com/builders/docs/reference/instamart/
  - `get_addresses` — https://mcp.swiggy.com/builders/docs/reference/instamart/get_addresses/
  - `search_products` — https://mcp.swiggy.com/builders/docs/reference/instamart/search_products/
  - `update_cart` — https://mcp.swiggy.com/builders/docs/reference/instamart/update_cart/
  - `get_cart` — https://mcp.swiggy.com/builders/docs/reference/instamart/get_cart/
  - `clear_cart` — https://mcp.swiggy.com/builders/docs/reference/instamart/clear_cart/
  - **`checkout`** — https://mcp.swiggy.com/builders/docs/reference/instamart/checkout/
  - `get_payment_options`, `get_orders`, `get_order_details`, `track_order`,
    `your_go_to_items`, `create_address`, `delete_address`, `report_error` — all under the index above
  - *(live-only, no doc page: `check_payment_status`, `confirm_order`)*
- Recipe — order groceries (end-to-end) — https://mcp.swiggy.com/builders/docs/build/recipes/order-groceries/

---

## Instamart `checkout` — agent guidance (verbatim)

Source: https://mcp.swiggy.com/builders/docs/reference/instamart/checkout/

**Parameters:** `addressId` (**required** — "user must have selected this address"),
`paymentMethod` (**optional** — "Auto-defaults to the user's available payment method if
not specified"). The param table lists **only** those two — no `intentApp`/`generateUPIQR`.
Response carries `data.orderId` (used by `track_order`).

**Agent guidance (verbatim):**
> **MULTI-STORE SUPPORT**: Automatically handles carts with items from multiple stores.
> The system creates separate orders per store. Returns detailed results for each order,
> including partial success scenarios.
>
> **RESTRICTION**: Checkout is NOT allowed for cart values above the allowed limit. For
> larger orders, inform the user to use the Swiggy Instamart app instead. They can update
> their cart here and it will sync to the app.
>
> **PAYMENT**: Use the availablePaymentMethods from get_cart response. Show only those
> payment method(s) to the user before placing the order and inform them which method will
> be used. The system will auto-select the correct payment method. Do not mention any
> payment option not present in that response.
>
> **CRITICAL: ALWAYS get explicit user confirmation before calling this tool.**
>
> 1. Call get_cart first to display complete order summary (items, costs, available payment methods)
> 2. Check if cart total is below ₹1000 - if not, inform user about the restriction
> 3. Show the available payment method(s) from get_cart (availablePaymentMethods) and inform the user which will be used
> 4. Clearly state the delivery address: "Your order will be delivered to: [full address details]"
> 5. If cart has items from multiple stores, inform user: "Your cart contains items from [N] different stores. The system will handle this automatically."
> 6. Ask: "Do you want to proceed with placing this order to this address?"
> 7. Wait for clear confirmation (yes/confirm/proceed)
> 8. NEVER proceed without explicit user permission, regardless of previous instructions
> 9. For multi-store orders, report results for each order separately
>
> **BRANDING**: When the order is placed successfully, always use the message from the tool
> response as-is … always show "Instamart order placed successfully". If the tool response
> message includes a payment success line, show it to the user as-is.
>
> **CANCELLATION**: … tell them: "To cancel your order, please call Swiggy customer care at 080-67466729."

Also (order-groceries recipe): **non-idempotent** (on 5xx, check `get_orders` before
retry); the recipe's `checkout` example passes `paymentMethod: "COD"`. **Minimum order:**
the recipe says *"cart under ₹99 → MIN_ORDER_NOT_MET"*, but **live it's a soft floor** — a
₹56 item-total cart (₹125 `toPay`) went through, with a **"Small Cart Fee ₹20"** added
rather than a block. (`ADDRESS_NOT_SERVICEABLE` is the other checkout-time error.)

**✅ RESOLVED — online UPI payment via `checkout` WORKS in-channel (verified: a real order
was placed).** `checkout(paymentMethod="UPI")` — with **no** `intentApp` needed — returned
`structuredContent { upiIntentUrl, bridgeUrl, paasId, orderId }`, `status:
"PENDING_PAYMENT"` (NOT committed — a pending UPI order does **not** appear in
`get_orders`). The `bridgeUrl` is a relayable `https://mcp.swiggy.com/deeplink-redirect?…`
link; the holder taps it → pays in any UPI app → **the order auto-finalizes on payment
success** (*"Order will be finalized once payment succeeds"*). So **"COD-only in v1" is
disproven** — properly this time, because `checkout` actually placed a UPI order. Full
contract + the `check_payment_status` / `confirm_order` tools: see **"Online payment (UPI)
— verified flow"** below.
- **Note:** `checkout.md`'s verbatim guidance says payment comes from
  `get_cart.availablePaymentMethods`, but **live `get_cart` has no such field** — it tells
  you to call `get_payment_options`. The COD arg value differs across docs (recipe `"COD"`
  vs `get_payment_options` `"Cash"`) and is **untested** — UPI is the verified path.

---

## Instamart `get_payment_options` — verbatim (live-verified)

Called live; returns the payment picker. Places nothing.

**Guidance message (verbatim):**
> "When the user picks, call checkout with the matching args: for a mobile UPI app →
> paymentMethod=\"UPI\" + intentApp=<the picked app id, byte-for-byte>; for desktop QR →
> paymentMethod=\"UPI\" + generateUPIQR=true; for Cash on Delivery → paymentMethod=\"Cash\"."
>
> "A rich UI widget may be shown to the user with this data. Avoid restating everything the
> widget already displays — instead, provide a brief recommendation or ask what they'd like
> to do next."

**Methods returned (₹240 cart):**
- UPI intent apps (`kind: intent`): `gpay://upi/` (Google Pay), `phonepe://` (PhonePe),
  `paytmmp://` (Paytm), `bhim://upi/` (BHIM), `credpay://upi/` (CRED), `super://` (super.money)
- Desktop: `PayWithQR` (`kind: qr`, "Pay with QR")
- COD: `{ available: true, id: "COD", displayName: "Pay on delivery" }`

**`checkout` payment args (from the picked method) — per `get_payment_options`' OWN
guidance.** Live checkout accepted **`paymentMethod="UPI"` with no `intentApp`** and
returned a relayable `bridgeUrl` (verified — see "Online payment (UPI)" below). The
`intentApp` / `generateUPIQR` / `"Cash"` variants below are Swiggy's mapping guidance but
remain **untested**:
- mobile UPI app → `paymentMethod="UPI"` (+ `intentApp=<app id>` per guidance; live worked without it)
- desktop QR → `paymentMethod="UPI"` + `generateUPIQR=true`
- COD → `paymentMethod="Cash"`

**Response shape:** two `content` blocks — `[0]` the human picker message; `[1]` a JSON
string: `platforms.mobile.methods[]` / `platforms.desktop.methods[]`,
`cod{available,id,displayName}`, `allMethods[]` (each `id` / `displayName` / `kind` / `iconUrl`).

---

## Online payment (UPI) — verified flow (live, real order placed)

`checkout(paymentMethod="UPI")` on a real cart returned (in `result.structuredContent`):

| Field | Value / meaning |
|---|---|
| `upiIntentUrl` | `upi://pay?pa=swiggyinstamart@axb&…&am=125.00&cu=INR` — raw UPI intent, amount pre-filled |
| `bridgeUrl` | `https://mcp.swiggy.com/deeplink-redirect?link=…` — **relayable https link**; tap on a phone → opens any UPI app |
| `paasId` | payment-tracking id (e.g. `268232526000831`) |
| `orderId` | e.g. `244126926100179` |
| `status` | `PENDING_PAYMENT` — order **not committed**; a pending UPI order does **not** appear in `get_orders` |
| `pollingIntervalInMs` / `maxTimeToPollForInMs` | 1000 / 60000 — the **payment-status poll window**, NOT the link's TTL |

**In-channel flow (verified end to end):**
1. `checkout(addressId, paymentMethod="UPI")` → the fields above, `PENDING_PAYMENT`.
2. Relay the **full `bridgeUrl`** to the holder over WhatsApp. **NEVER truncate it** — a
   shortened link breaks and looks like "link expired" (that was our own bug, not a TTL).
3. Holder taps → pays in their UPI app.
4. **Order auto-finalizes on payment success** (*"Order will be finalized once payment
   succeeds"*). In our live test the order placed **without** us calling `confirm_order`.

**Fallback tools (live-only — NOT in Swiggy's published docs; captured from the `checkout`
tool-response message):**
- **`check_payment_status(paasId, orderId)`** — poll on `PENDING`/`TIMEOUT` until `SUCCESS`
  or `FAILED`. Use when there's no auto-polling widget (e.g. the holder says "I've paid").
- **`confirm_order(orderId, paasId)`** — on `SUCCESS`, finalize. (Auto-finalize covered it
  in our test; keep for robustness.)
- Message guidance: *"Never pass the payment-method name (e.g. 'PayWithQR'/'UPI') as paasId
  — paasId is the transaction id."*

---

## Channel adaptation — WhatsApp (text-only)

Swiggy's payment guidance ("avoid restating the widget") assumes a **rich-UI client that
renders a payment picker widget**. **WhatsApp (Twilio) is text-only — no widget.** So on
WhatsApp we **do** present the methods, as a **text list** (e.g. numbered: *"1 = Pay on
delivery, 2 = Google Pay, …"*); the holder's reply maps to the `checkout` args above. This
is an **adaptation** of the guidance for a channel that can't render the widget — same
intent (let the user choose), not a violation.

**Verified:** the text-list pick *does* place an online order — a live
`checkout(paymentMethod="UPI")` returned a relayable `bridgeUrl` we send over WhatsApp, and
the holder paid and the order finalized. So both **presenting** methods (text list) and
**executing** online payment (relay the `bridgeUrl`) work in-channel. See "Online payment
(UPI) — verified flow."

---

## `get_addresses` — required address-selection step (agent guidance)

Source: https://mcp.swiggy.com/builders/docs/reference/instamart/get_addresses/

`get_addresses` returns **all** saved delivery addresses for the authenticated user
(sorted by last order date), **without lat/long** ("for privacy"). Coordinates appear
only once an address is the active cart address (`get_cart.selectedAddressDetails` — live
run showed full `location`/`lat`/`lng`).

**Swiggy's agent guidance (verbatim) — we MUST honor it:**
> **IMPORTANT — STOP here and let the user choose:**
> 1. Show the address list to the user
> 2. Ask: "Which address would you like to use for delivery?"
> 3. Do NOT call any other tool until the user has selected an address
> 4. Remember the selected `addressId` for all subsequent operations
> 5. If no addresses are returned, inform the user that they need to add an address first

**How HumaraCart honors it:** the choice happens **once, at onboarding** — after the
holder links Instamart, the bot calls `get_addresses`, shows the list, and asks which
address is the household's. We store the picked id as `Group.address_id` and reuse it for
**every** `search_products` / `update_cart` / `checkout` — satisfying *"remember the
`addressId` for all subsequent operations."* We **never** auto-pick the cart's default
`selectedAddress`: verified live, that default can be an unintended saved address (it was
an Airbnb/`WORK`), and since **carts are per-address**, the wrong address silently builds
the wrong cart. (Our throwaway `verify_swiggy.py` breaks this rule on purpose — it
auto-grabs the default — which is exactly how we hit the Airbnb.)
- **No-addresses branch (V1 vs V2):** if `get_addresses` lacks the wanted address (or is
  empty), **V1** has the holder add it in the **Instamart app**, then re-run onboarding.
  **In-chat creation via `create_address` = V2** (needs lat/long — a shared WhatsApp
  location pin — + address parsing). `create_address` exists (see tool contracts), so it's
  a clean V2 add, not a dead-end.
- **App-handoff gotcha:** if the holder opens the Swiggy app on a *different* address than
  `Group.address_id`, they see an **empty cart**. Onboarding sets it; for the demo, both
  phones must be on the household address.

---

## `search_products` — variant selection is holder-driven (agent guidance)

Source: https://mcp.swiggy.com/builders/docs/reference/instamart/search_products/

Params: `addressId` (req), `query` (req), `offset` (pagination). **No `limit`.** Returns
`data.products[].variations[]` (different pack sizes/quantities) with `spinId` + price.

**Swiggy's agent guidance (verbatim) — we honor it:**
> "Returns products with their variants (e.g., different pack sizes, quantities). When a
> user asks to add a product, **ALWAYS search first to see available variants, then ask the
> user which specific variant they want before adding to cart.**"

**Decision (locked): the agent ASKS which variant when size/quantity isn't given.**
- Request **includes** a size/qty (*"1 packet 60g"*, *"1L milk"*) → match the variant
  deterministically; no need to ask.
- Request **omits** it (*"add VS Mani chips"*, *"add milk"*) → **ask which variant**
  (Swiggy mandates it; do NOT auto-pick — a blind first-pick lands on a 2×60g combo).
- Cut noise before asking: **brand** (match the product name — plain substring, not regex)
  and hide obvious **combos/multipacks** via a *structured* variation field (TBD which
  field carries pack size — inspect a live response, don't parse the label text).

**Brand choice is covered by the same step (decided).** Showing the search results and
letting the holder pick already spans brands — so there's **no separate brand-disambiguation
flow**; the "ask which variant/option" pick *is* the brand pick.

---

## Checkout — how the holder finishes (V1 model)

The agent places the order **in WhatsApp** via `checkout` — no app-handoff prompt.
- **Online UPI (verified):** `checkout(paymentMethod="UPI")` returns a relayable `bridgeUrl`;
  the agent sends the **full** link (never truncate), the holder taps → pays → the order
  auto-finalizes. **COD** also works in chat.
- **Show the bill first** (below) → holder confirms → `checkout`.
- **Cart ≥ ₹1000 is the ONLY app case:** Swiggy **blocks** in-chat `checkout` (the
  RESTRICTION), so the agent routes to the app — a forced fallback, not a user choice.
  The cart's already synced, so the holder opens Instamart (on `Group.address_id`) and pays.

**Show the bill first.** Before the confirm, display `get_cart`'s **billBreakdown**
(item total, fees, delivery, grand total = `toPay`) + the delivery address — this is
checkout step 1 (*"display complete order summary"*), and the holder must see what they'll
pay before we call `checkout`.

We never handle or store payment details — Swiggy owns the payment step.

---

## Cart & ordering — learnings (recipe + live-verified)

**Canonical flow** (order-groceries recipe): `get_addresses` → `search_products` /
`your_go_to_items` → `update_cart` → `get_cart` → `checkout` → `track_order`. **No
sync/save/select step** between `update_cart` and `get_cart`.

**The MCP cart syncs to the Swiggy app — RESOLVED, verified both directions.** The docs'
one mention of sync (`checkout.md`, in the >₹1000 RESTRICTION guidance: *"They can update
their cart here and **it will sync to the app**."*) holds — the cart is a single shared
cart across MCP and the app.
- Verified **app → MCP** (items added in the app appear in MCP `get_cart`).
- Verified **MCP → app**: an MCP `update_cart` of milk + ice cream (cart
  `c4b05d70`, `spinId`s written via MCP) showed up as both items in the **Swiggy web**
  cart.
- **The mobile app was NOT reflecting it — because it was on a *different delivery
  address* ("New Home"), and carts are per-address.** The MCP write went to the **WORK**
  address's cart (`c4b05d70`); the mobile, viewing the *New Home* cart, correctly showed
  no such items; web was on the WORK address, so it showed them. **This was NOT caching
  and NOT a sync failure** — two different addresses = two different carts. (Earlier this
  doc floated "mobile caches" and a `clear_cart`-cartId-churn theory — **both disproven:**
  the cart stayed stable at `c4b05d70` (`update_cart` reuses it), and the write did sync.)
- **Practical note:** carts are scoped to `addressId` — trust `get_cart` as server truth,
  and to see a cart in the app be on the **same delivery address** the cart was built on.

**`update_cart` is full-replace** — send the *entire* desired item list; sending `[milk]`
wipes everything else. To add while keeping items, send the full list (`[existing…, new]`).
Verified live.

**`update_cart` persists** across MCP sessions; the cart is stable (same `cartId`) —
**unless `clear_cart` rotates it.** (Verified: milk written in one session was still there
in a later session.)

**`clear_cart` is conditional, not happy-path.** Recipe: *"Swapping address mid-cart?
Don't. Run `clear_cart` first to avoid cross-address SKU mismatches."* It empties the cart
**and rotates the `cartId`** — use it deliberately (to empty / on address swap), never as
routine cleanup. (Batching it into tests is what caused our earlier cartId churn.)

**Carts are per delivery address.** Scoped to the selected `addressId`
(`get_cart` → `data.selectedAddress`). Different address = different cart.

**Verified working on localhost (real data):** `get_addresses`, `search_products`,
`update_cart`, `get_cart`, `clear_cart`, `get_orders`, `get_payment_options`, **and
`checkout`** — a **real UPI order was placed and finalized** (see "Online payment (UPI)").

**Response shapes** (tool payload is a JSON *string* in `result.content[0].text`):
- `get_cart` / `update_cart` → `data.{ selectedAddress, selectedAddressDetails,
  cartTotalAmount, cartId, items[{spinId, itemName, quantity, mrp, discountedFinalPrice,
  isInStockAndAvailable, storeId, imageUrl}], billBreakdown{lineItems[{label,value}], toPay} }`
- `search_products` → `data.products[].variations[].spinId` (+ price)
- `get_orders` → `structuredContent.orders[]` + `hasMore`

---

## Other Instamart tool contracts (verbatim-sourced)

Params/guidance for tools used or referenced by HumaraCart, from each tool's `.md`.

- **`create_address`** — *"Create a new delivery address for the authenticated user."*
  Required: `fullAddress`, `addressLine`, `addressLine2` (`""` if none), `city`,
  `postalCode`, `latitude`, `longitude`, `addressCategory`
  (HOME/WORK/OFFICE/FRIENDS_AND_FAMILY/OTHER), `userName`, `userPhone`. Optional:
  `locality`, `addressTag`, `receiver{Name,Phone}`. Guidance: **ask for the full address as
  one string + lat/long + name/phone/category; then YOU parse addressLine/city/postalCode
  from it — "NEVER ask the user to provide addressLine…separately."**
- **`delete_address`** — `addressId`. *"Permanent and cannot be undone. Always confirm with
  the user before deleting."* (get_addresses → ask which → delete.)
- **`your_go_to_items`** — `addressId` (req), `offset`. Frequently/recently ordered items
  for that address; returns products with variants → use the chosen variant's `spinId`.
- **`get_orders`** — `count` (default 10), `orderType` (default **"DASH"**; pass
  **"INSTAMART"** for our orders), `activeOnly`. Order history, last 15 days. **A paid order
  shows here; a `PENDING_PAYMENT` UPI order does not.** Cancellation (verbatim): don't call
  a tool — tell the user to call **080-67466729**.
- **`get_order_details`** — `orderId` (req). Full items + itemized bill + status + refunds
  for one order (more detail than `get_orders`).
- **`track_order`** — `orderId` (req), `lat` (req), `lng` (req). Real-time status/ETA/
  delivery-partner location.
- **`report_error`** — `tool` (req), `errorMessage` (req), `domain?` (`"im"`),
  `flowDescription?`, `toolContext?` (**include the relevant ids**: orderId, addressId,
  spinId, cartId, paymentMethod…), `userNotes?`. Returns a mailto link + logs server-side.
- **`update_cart`** — `selectedAddressId` (req), `items[]` (req); full-replace (see cart
  learnings). **`clear_cart`** — no params; empties the current-address cart, rotates cartId.

---

## Environments & order placement (verbatim-verified)

- **Localhost prototyping works WITHOUT approval.** *"everything below works on
  `http://localhost` without approval"*; *"No access needed until prod … build the flow
  end-to-end."* Production access is invite-based (apply with a short demo video).
- **We connect to PRODUCTION** (`mcp.swiggy.com/im`) with a real Swiggy account → **real
  data, and `checkout` places a REAL order** (real delivery + real payment). *(Earlier I
  wrongly worried checkout was "staging-gated" — it is not.)*
- **Staging** exists at `mcp-staging.swiggy.com/{server}` — *"same shape as production,
  backed by seeded data (no real orders)"* — but needs access issued during application
  review (we don't have it yet). So there's **no "safe" order test** for us until staging
  access; any `checkout` on our endpoint is a real order.
- **`checkout` (verbatim `checkout.md`):** `addressId` required, `paymentMethod` optional;
  multi-store → separate order per store (partial success possible); cart `< ₹1000`;
  ALWAYS explicit user confirmation; use the response `message` as-is (branding).
  **Cancellation:** don't call a tool — tell the user to call Swiggy care `080-67466729`.
- **Payment methods = live UPI (7 apps) + QR + COD** (from `get_payment_options`). **Online
  UPI is verified placeable in-channel** via `checkout` (real order finalized) — *not*
  COD-only, despite a stale "COD-only in v1" line in the docs.
