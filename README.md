# HumaraCart: A Collaborative Household Instamart Assistant
### Swiggy Builders Club: Developer Program Application

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

HumaraCart maintains a running cart for the household. No one has to remember. No one has to open Instamart. When the list feels ready, any member nudges the account holder. The account holder reviews, makes last minute changes, and gets a direct Instamart cart link to checkout. That is it.

This is the vision.

---

## The Challenge

WhatsApp Business API does not natively support group bots. A bot cannot be added as a member of a WhatsApp group.

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
- The bot generates an invite link with a JWT token encoding the household ID, expiry, and a tamper-proof signature. The account holder forwards this to other members.
- New members tap the link, WhatsApp opens with the token prefilled, and the bot adds them to the household. Expired or already-used tokens are rejected.
- The bot greets new members: *"Welcome to HumaraCart, powered by Swiggy Instamart. You have joined Priya's Household. Orders are fulfilled by Instamart via Priya's account. You do not need one."*
- Brand preferences are configured upfront for common items.

**Day-to-day usage:**
- Any member messages the bot: `add milk`, `add detergent 2`, `add chips`, `remove milk`, `show list`
- If quantity is missing, the bot asks: `How many?`
- If there is a brand conflict, the bot asks rather than assumes: `Which brand of milk?`
- The bot uses Swiggy's Instamart MCP tools to search items, resolve brands, and build the cart on behalf of the household.

**Ordering:**
- Any member can nudge the account holder: `ready to order`. The bot forwards it: *"Priya thinks the cart is ready. Want to review?"*
- The account holder sends `send cart link`. The bot sends a full summary first.
- The account holder makes any last minute changes. Once satisfied, they send `confirm`.
- The agent builds the cart on Instamart via MCP on behalf of the account holder. If a shareable cart link is available via the MCP, it is sent directly. Otherwise the account holder is notified to open Instamart where their cart is already populated.
- The account holder checks out on Instamart directly. The agent's job ends at cart creation.
- Delivery updates are shared with all household members via the bot.

**Household management:**
- Members can be added or removed at any time.
- Switching households creates a new group ID on the backend. Before creation, the backend checks if a household with the same members already exists to avoid duplicates.
- Households are fully isolated. No cross-household visibility.

---

## The Trust Arc

**V1: Collaborative Cart**
Agent builds the cart from household inputs. Account holder reviews and checks out via Instamart. Trust is established.

**V2: Household Intelligence**
- Agent learns from order history and identifies purchase patterns. Reminds: *"You usually buy milk every 5 days. It has been 4 days. Want to add it?"*
- Nudges the account holder when the cart has been idle: *"You have 5 items in your cart. Ready to order?"*

**V3: Auto-Order (opt-in)**
Routine items can be set to auto-order for users who have explicitly granted the agent permission. Fully opt-in and item-specific.

Each stage earns the next. Trust is not assumed. It is built incrementally.

---

## Why This Matters for Swiggy

Most Instamart use cases optimise for the individual user. HumaraCart treats the **household as the unit**, which is how grocery shopping actually works in India.

- **Higher order value:** a cart built by 3-4 people is larger than a cart built by 1
- **Higher retention:** shared utility is stickier than individual utility; churning means letting your household down
- **Reduced browse friction:** users never open the app to search; the agent handles discovery via Swiggy's MCP tools
- **V3 auto-order:** routine household replenishment becomes a recurring GMV stream with zero active user effort

This is not a chatbot for Instamart. It is a new interface layer for how households shop.

---

*Built on Swiggy Instamart MCP | Contact: mridubhatnagar4@gmail.com*
