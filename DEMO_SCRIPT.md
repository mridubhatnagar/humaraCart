# HumaraCart — Demo Recording Script

Operational runbook for the actual recorded take. Supersedes `IMPLEMENTATION_PLAN.md`
§11 for recording logistics — the message script and payment handling below reflect
decisions made during rehearsal that the original plan didn't anticipate. Household:
**Priya** (account holder, `+918562851868`) + **Rahul** (member, `+919131477479`).

---

## Recording setup

- **Priya:** her actual phone, native Android screen recorder (Quick Settings →
  Screen Record). Handles the whole flow including the UPI payment tap natively —
  no browser/desktop mismatch, no login-page fallback.
- **Rahul:** WhatsApp Web in a browser on desktop, screen-recorded. Crop out the
  left contact-list sidebar afterward with ffmpeg (it doesn't collapse at narrow
  window widths, so cropping in post is needed, not a live resize).
- Combine both clips side by side afterward via `ffmpeg`'s `hstack` filter.
- **Onboarding/invite flow is NOT shown live** — showing the invite link or OAuth
  screen live would expose real contact details/personal info. That part is
  covered separately by `invite_flow.pptx` (on the Desktop), not this recording.

---

## Pre-flight checklist (do immediately before hitting record, not hours before)

1. OAuth token fresh (<5 days old) — reseed via `scripts/seed_household.py` if not.
2. **Freeze on non-bot touches to the real Swiggy account** from now until the
   take is done: no re-running `verify_swiggy.py`/`verify_mcp_client.py`, no
   opening the real Swiggy app on this address. Every cart-mismatch surprise
   during rehearsal traced back to one of these.
3. Clear local `ItemCart` rows for the household + call the real `clear_cart()`,
   confirm the live cart is genuinely empty (`get_cart` → `items: []`).
4. Run `show cart` once as a final smoke test — real names/prices (or "empty")
   means clean; raw spin_id codes mean something touched the cart and it needs
   re-clearing before recording starts.
5. Both phones joined to the Twilio sandbox; check the rolling 24h message
   quota has enough headroom for a full take plus retakes.

---

## Message script (11 turns, in order)

1. **Priya:** `add 1L milk`
2. **Rahul:** `add 1kg detergent`
3. **Rahul:** `add 1L milk` → *"already on the list (added by Priya)"* — **the money shot, duplicate-catch**
4. **Priya:** `lets get some chips` → bot asks "which one?" since chips has no size specified
5. **Priya:** *(reply with the chips variant number)*
6. **Rahul:** `remove detergent`
7. **Rahul:** `show list`
8. **Rahul:** `ready to order` → nudges Priya
9. **Priya:** `checkout` → bot shows the bill + payment options
10. **Priya:** `UPI`
11. **Priya:** *(taps the real payment link — see Payment handling below)*

---

## Payment handling (UPI)

- After step 10, the bot sends a real, relayable `bridgeUrl` payment link —
  showing this on camera is real proof the order is genuine, not mocked.
- **GPay (and most UPI apps) block screen recording** (`FLAG_SECURE`) — the
  recording will go black the moment the UPI app opens. Don't try to record
  through it.
- **Pause the recording right after the link appears on camera.** Pay off-camera
  in your own time. **Resume recording once the "order placed" confirmation
  broadcasts to both phones** — that's the moment that actually matters for the
  demo, not the payment app screen itself.
- COD was considered as a way to avoid this entirely, but was rejected — showing
  the real UPI link is worth keeping; only the in-app payment moment gets cut
  around, not the whole payment method.
