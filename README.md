# HumaraCart: A Collaborative Household Instamart Assistant
### Swiggy Builders Club: Developer Program Application
### Running on Swiggy's Instamart MCP

Full application — architecture, MCP integration, security model, roadmap: [mridulabs.dev/swiggy-builders-club-application](https://mridulabs.dev/swiggy-builders-club-application)

---

## The Problem

In a shared household, everyone has needs but no one has full visibility. Person 1 orders milk not knowing Person 2 already ordered it. Person 3 forgets to tell anyone they used the last of the detergent. Items get duplicated, items get missed, and the coordination happens after the fact.

The problem is not Instamart. The problem is there is no shared layer, no single view of what the household needs. Each person is ordering in isolation.

---

## The Idea

Picture a WhatsApp group: three flatmates, one shared address. There is a fourth member in the group, HumaraCart, an AI assistant.

Throughout the day, as people notice things running low, they just say it:

- Priya: `add milk`
- Rahul: `add detergent`
- Sneha: `add chips`
- Rahul: `remove detergent`
- Sneha: `show list`
- HumaraCart: `Current list: milk, chips`

HumaraCart maintains a running cart for the household. No one has to remember. No one has to open Instamart. When the list feels ready, any member nudges the account holder. The account holder reviews, makes last minute changes, confirms, and the bot places the order — bill, payment, and all — right inside WhatsApp. That is it.

This is the vision.

---

## The Workaround

Each household member has a 1:1 conversation with the bot. On the backend, all members are mapped to a shared household group ID. Every addition is reflected in one unified list. Members who opt in receive the updated list after every addition.

The user experience is identical to the group vision. The difference is only under the hood. This approach works fully within the official WhatsApp Business API. No unofficial libraries. No ToS risk.

---

## Why WhatsApp

WhatsApp is where Indian households already communicate. Any channel that requires a new app or a new habit creates drop-off before the product gets a chance. WhatsApp is not a technical convenience. It is where the user already is.

---

## How It Works

**Setup (done once by the account holder):**
- The account holder saves the HumaraCart number, initiates a chat, and links their existing Instamart account via OAuth. No new account needed.
- The bot generates a secure invite link. The account holder forwards this to other members.
- New members tap the link, WhatsApp opens, and the bot adds them to the household.
- The bot greets new members: *"Welcome to HumaraCart, powered by Swiggy Instamart. You have joined Priya's Household. Orders are fulfilled by Instamart via Priya's account. You do not need one."*
- During setup the bot shows the account holder their saved Instamart addresses and asks which to use for the household — every order delivers there. (Swiggy requires the user to pick the delivery address.)

**Day-to-day usage:**
- Any member messages the bot: `add milk`, `add detergent 2`, `add chips`, `remove milk`, `show list`
- If the size or brand isn't specified, the bot shows the matching options and the member picks — Swiggy requires confirming the exact variant before adding to cart, so this doubles as brand selection.
- The bot uses Swiggy's Instamart MCP tools to search items and build the shared cart on behalf of the household.

**Ordering:**
- Any member can nudge the account holder: `ready to order`. The bot forwards it: *"Priya thinks the cart is ready. Want to review?"*
- The account holder sends `checkout`. The bot shows the full bill (items, fees, total) and delivery address, and lists the available payment methods.
- The account holder confirms and picks a method. For **UPI**, the bot sends a payment link right in WhatsApp — one tap, pay in any UPI app, and the order is placed (it finalizes automatically once payment succeeds). **Cash on delivery** also works.
- The whole flow — cart, confirmation, payment, order — happens **inside WhatsApp**. No one opens Instamart. (The one exception: a cart over ₹1,000, where Swiggy requires checkout in the app.)
- Delivery updates are shared with all household members via the bot.

**Household management:**
- Members can be added or removed at any time.
- Switching households creates a new group ID on the backend. Before creation, the backend checks if a household with the same members already exists to avoid duplicates.
- Households are fully isolated. No cross-household visibility.

---

## Tech Stack

| Layer | Choice |
|-------|--------|
| Backend | Python, FastAPI |
| Agent | LangGraph (ReAct) — the agent does NL understanding **and** tool selection in one step; no separate intent-classification stage |
| LLM | OpenAI GPT-4o (via `ChatOpenAI`) |
| MCP Client | Swiggy Instamart MCP — real production `/im` (localhost prototyping needs no approval) |
| Swiggy APIs | TBD. Depends on what is available and exposed (e.g. order tracking) |
| Messaging | Twilio Sandbox for WhatsApp (V1); WhatsApp Business API (V2) |
| Database | SQLite (V1; Postgres later is a connection-URL change) |
| Cache / Observability | Deferred (Redis, LangSmith) — not needed for V1 |
| Infrastructure | Docker |
| Hosting | Local for V1 (laptop + ngrok or cloudflared tunnelling the Twilio webhook); DigitalOcean for V2+ |

The backend acts as the MCP client, receiving WhatsApp messages, resolving household context, and making Instamart MCP tool calls to search products and manage the shared cart.

---

## Getting Started

**Prerequisites:** a Twilio account with the [WhatsApp Sandbox](https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn) joined, and an OpenAI API key.

```bash
cp .env.example .env.local        # fill in Twilio, OpenAI, JWT secret (see comments in the file)
ngrok http 8000                   # separate terminal, keep it running — copy the forwarding URL
docker compose run --rm test      # offline suite — mock Instamart, in-memory DB
docker compose up app             # serves on :8000
```
Set `OAUTH_REDIRECT_URI=<ngrok-url>/oauth/callback` in `.env.local`, and point the Sandbox's webhook (Messaging → Settings → "When a message comes in") at `<ngrok-url>/webhook`.

Then message the Sandbox number to onboard as the account holder — no seed data needed. (`scripts/seed_household.py` is a local-dev shortcut for the same OAuth login, skipping the WhatsApp round trip.)

---

*Built on Swiggy Instamart MCP | Contact: [mridubhatnagar](https://www.linkedin.com/in/mridu-bhatnagar-17703a92/)*

