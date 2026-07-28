# HumaraCart — Build TODO

Actionable checklist for the V1 demo build. Derived from `IMPLEMENTATION_PLAN.md`
§9 (build sequence, riskiest-first), §13 (open items), and the locked decisions in
`CLAUDE.md` / the demo-plan memory. Order roughly follows the plan; check items off
as they land. Both external deps (MCP + WhatsApp) are already de-risked — see
`VERIFICATION.md`.

---

## Done (de-risking + prior work)

- [x] Core `CartService` + 19 tests (household logic, sitting aside) — step 0
- [x] Twilio round-trip **+ broadcast to 2nd phone** on real phones (`scripts/verify_twilio.py`) — step 1
- [x] MCP dependency proven vs real Instamart: OAuth + search + update + **real order placed** (`scripts/verify_swiggy.py`) — step 2 (dependency)
- [x] Online **UPI** checkout verified in-channel (relayable `bridgeUrl` → pay → auto-finalize)
- [x] Cart per-address scoping / sync resolved
- [x] Full plan, DB design, reference, sequence diagram, README reconciled

---

## Step 2 — MCP client (`InstamartClient`)

Dependency is proven; the production class is not built yet.

- [ ] `IInstamartClient` ABC — the seam `CartService` and the agent depend on
- [ ] `McpInstamartClient` (real `/im`, sync) — OAuth PKCE (`client_id=swiggy-mcp`), token exchange/refresh
- [ ] Token store: encrypted-at-rest (Fernet, key from env), nullable fields per `DB_DESIGN.md`
- [ ] Defensive parsing of `result.content[0].text` / `structuredContent` envelopes
- [ ] Verify at build: `refresh_token` obtainability; `get_cart` inner field names (open item #5)
- [ ] `MockInstamartClient` kept as the offline unit-test double

## Foundation — DB / DAO / config

- [ ] SQLAlchemy models: `Account`, `Group`, `GroupAccount`, `ItemCart`, `InviteToken` (per `DB_DESIGN.md`)
- [ ] `IDAO[T]` base + per-entity DAOs (`AccountDAO.get_by_phone`, `GroupDAO`, …) — ORM only, no raw SQL
- [ ] `pydantic-settings` config object (secrets/tokens from env, never hardcoded)
- [ ] FastAPI app skeleton: `app/main.py` + routers, `app/dependencies.py`
- [ ] Docker + docker-compose (SQLite on a mounted volume), `pytest` test container

## Step 3 — Rewire `CartService` → `InstamartClient`

- [ ] Refactor the 19 `CartService` tests from `add_item`/`remove_item` to the **guard interface**
- [ ] Guard builds the `update_cart` **full-replace payload from local `ItemCart`** (local-as-truth)
- [ ] Attribution = message sender (`From` → member, plain Python — no diff, no LLM)
- [ ] Dedup + broadcast decisions live in the guard
- [ ] Serialize per-household read-modify-write (update_cart is full-replace)

## Step 4 — The Agent

- [ ] Custom LangGraph `StateGraph` — tool-calling **LOOP** (observe each MCP result → re-reason)
- [ ] Agent binds the MCP tools **directly** (search_products / update_cart / get_cart / get_payment_options / checkout) — no wrapper tools
- [ ] `interrupt` for human-in-the-loop: variant pick, checkout confirm, address pick
- [ ] Deterministic write-guard wraps every cart write
- [ ] Swappable `ChatOpenAI` (GPT-4o), `temperature=0`
- [ ] **Design the agent system prompt** (highest-leverage — open item #3)
- [ ] Expand the "world says no" scenario list (§7 living list) into prompt coverage: out-of-stock, not-serviceable, no-match, min-order, cart ≥ ₹1000, address-not-saved → V2
- [ ] Enforce checkout rules: bill first (`get_cart` billBreakdown), total `< ₹1000` else app-fallback, explicit confirm + state address, payment options from `get_payment_options` (never fabricated)

## Step 5 — Webhook glue + broadcast

- [ ] `/webhook` router: Twilio signature verification (dependency), resolve member↔household from inbound number
- [ ] Fast-ack webhook + background task (Twilio ~15s timeout)
- [ ] `Messenger` interface: `ConsoleMessenger` (dev) + `TwilioMessenger` (real); reply + broadcast via REST
- [ ] Broadcast the updated list to opted-in members after each change

## Step 5b — Invite / onboarding flow

- [ ] Holder onboarding: OAuth link → `get_addresses` → **STOP & ask** → store `Group.address_id`
- [ ] `invite`: signed, single-use, expiring JWT (household id + expiry)
- [ ] Member join: validate token, mark consumed in `InviteToken` ledger, add to household, greet
- [ ] Dedup by phone; reuse account, never recreate

## Step 6 — Recording instrumentation

- [ ] Tool-call logging for the "under the hood" terminal shot

## Step 7 — Dry run

- [ ] Run the locked demo script (§11) end to end on both phones
- [ ] Pre-flight checklist: OAuth token fresh (<5 days), both phones joined to sandbox, `get_addresses` returns a valid `addressId`
- [ ] scrcpy side-by-side + screen recording setup

---

## Review cadence — milestones, not per-edit

Review happens at **milestone boundaries**, not on every edit. Each milestone ends
in a verifiable state (tests green or something runs), so review is "does this hold
up," not "read every line." Ordered; each builds on the last.

| M | Milestone | Reviewable when | Model | Needs you |
|---|---|---|---|---|
| **M1** | **Foundation** — FastAPI skeleton, settings, 5 SQLAlchemy models, `IDAO` + DAOs, Docker, pytest wired | app boots; DAO tests green | Sonnet | template gate (see below) |
| **M2** | **MCP client** — `IInstamartClient` ABC, `McpInstamartClient` (lifted from `verify_swiggy`), `MockInstamartClient`, Fernet token store | mock tests green; one live smoke call | Sonnet | maybe a login |
| **M3** | **Cart engine on the real seam** — `CartService` → guard interface, full-replace-from-local, attribution=sender, dedup, 19 tests refactored | all cart tests green | Sonnet | — |
| **M4** | **Transport + onboarding** — `/webhook`, signature verify, member↔household resolve, fast-ack + background, `Messenger` (Console+Twilio), JWT invite flow | end-to-end via `ConsoleMessenger` locally | Sonnet | — |
| **M5** | **The agent** — StateGraph loop, direct MCP tools, interrupts, **system prompt** | agent drives a scripted flow | Opus | iterate w/ you |
| **M6** | **Dry run** — tool-call logging, two-phone run, recording | locked script runs clean | — | phones/recording |

**M1 is a "review the template, then mass-produce" gate.** First deliverable is one
thin vertical slice — `Account` model + `AccountDAO` + its tests — so the DAO/`IDAO`
shape gets sanity-checked **once**. Approve the pattern, then the other 4 entities
get replicated without re-reviewing each.

**M5 is not a single clean gate** — the system prompt needs a few iteration rounds
with live runs; treat it as a milestone with an interactive sub-loop.

---

## Model strategy

The hard reasoning is already locked in the docs, so most of the build is execution
against a detailed spec — cheaper/faster on **Sonnet**. Flip to **Opus** for the
judgment-heavy parts. Switch anytime with `/model`.

- **Sonnet** — step 2 `InstamartClient`, Foundation (DB/DAO/config/skeleton/Docker), step 3 rewire, step 5/5b glue + onboarding, step 6/7 plumbing.
- **Opus** — step 4 **agent** (StateGraph loop, `interrupt` wiring, and the **system prompt** — open item #3), and the **guard interface** design + 19-test refactor (correctness lives here).
- Signal to flip back to Opus mid-step: repeated review friction (correcting the same things).

---

## Guardrails (apply throughout)

- Sync `def` handlers only — no async, anywhere.
- Controller → service → DAO → DB; thin routers, fat services; no logic in handlers.
- No banner comments. No hardcoded secrets. LLM stays out of correctness-critical paths.
- Follow Swiggy's MCP agent guidance verbatim (`REFERENCE.md`); use their tool `message` fields as-is.
