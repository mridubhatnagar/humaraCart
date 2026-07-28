# HumaraCart — Verification Log (de-risking)

What's been proven **live** before writing the product, and how to reproduce it. Both
external dependencies — the Swiggy Instamart MCP and the WhatsApp transport — are verified,
so the remaining work is code we control.

Throwaway diagnostics live in `scripts/` (**NOT** product code): `verify_swiggy.py`,
`verify_twilio.py`. Stdlib only, no pip install.

---

## 1. Swiggy Instamart MCP — VERIFIED (real order placed)

Endpoint `POST mcp.swiggy.com/im`, OAuth 2.1 PKCE, real production data. Proven end to end:

- `get_addresses` (holder-driven selection), `search_products` (variant pick),
  `update_cart` (full-replace, per-address), `get_cart` (bill), `get_payment_options`,
  and **`checkout`** — a **real UPI order was placed and finalized** (relay `bridgeUrl` →
  holder pays → auto-finalizes).
- Full learnings + verbatim agent guidance: **`REFERENCE.md`**.
- Reproduce: `python3 scripts/verify_swiggy.py` (browser login); `… cart` (read-only cart
  check); `… checkout` (real order — typed-`YES` gated).

## 2. WhatsApp transport (Twilio Sandbox) — VERIFIED

The one unproven dependency before this. Proven via `scripts/verify_twilio.py`:

- **Inbound webhook** — a WhatsApp message reaches our local server (Twilio → ngrok tunnel
  → `/webhook`).
- **Outbound reply** — we reply to the sender via Twilio's REST API.
- **Broadcast** — a message from phone A reaches **phone B** (the household mechanic — the
  key thing).

**Setup used:**

- Twilio WhatsApp **Sandbox** (shared number — no purchased number needed). Both phones
  joined by sending `join <code>` to the sandbox number.
- Creds via **env vars** (never hardcoded): `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
  `TWILIO_WHATSAPP_FROM`, `PHONE_A`, `PHONE_B`.
- `ngrok http 8000` tunnels Twilio → the local server; the tunnel URL + `/webhook` goes in
  **Sandbox settings → "When a message comes in"** (method POST).

**Gotchas learned (will bite again on the build's real WhatsApp runs):**

- **ngrok free changes the URL on every restart** → re-paste the new `<url>/webhook` into
  Sandbox settings each time. A stale URL makes Twilio serve its default *"Configure your
  Sandbox's Inbound URL to change this message"* reply — which means **our webhook isn't
  being hit** (not a code bug).
- **`401` / code `20003`** on outbound = wrong or mismatched Account SID + Auth Token.
  Verify creds directly: `curl -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN"
  "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID.json"`.
- The script reads creds at **startup** — re-`export` then **restart** it after any change.
- 24-hour window / message templates: fine in-session for the demo; a production concern
  for proactive broadcasts to a member who's been quiet.

**Design implications (already in the plan):**

- Messaging sits behind a `Messenger` interface → **`ConsoleMessenger` in dev** (zero
  Twilio credit), `TwilioMessenger` for the real runs. Provider is swappable (Meta Cloud
  API / another BSP) if the trial credit (~$2.85) runs out.
- Real flow: **fast-ack webhook** (Twilio ~15s timeout) → **background task** → reply +
  broadcast via Twilio REST.

---

## Status

- **MCP:** ✓ verified (real order placed).
- **WhatsApp transport:** ✓ verified (round-trip + broadcast to both phones).
- **Recording rig (scrcpy + GNOME recorder):** deferred — decide later.
- **Remaining:** the product build — wire the proven agent + cart + MCP behind the proven
  WhatsApp layer.
