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

## Step 2 — MCP client (`InstamartClient`) — DONE

- [x] `IInstamartClient` ABC — redesigned to mirror real Swiggy tool shapes (`get_addresses`, `search_products(address_id, query)`, full-replace `update_cart`, `get_cart`, `clear_cart`, `get_payment_options`, `checkout`, `get_orders`); renamed from `InstamartClient` for `IDAO`-convention consistency. 3-way error taxonomy: `InstamartAuthError`/`InstamartDomainError`/`InstamartUpstreamError`.
- [x] `McpInstamartClient` (`app/instamart/mcp_client.py`) — real `/im` calls lifted from `verify_swiggy.py`'s proven logic; exponential backoff + jitter (500ms→8s, max 5 retries) on transient upstream errors; captures Swiggy's injected `message` field (`client.last_message`) rather than discarding it, per CLAUDE.md's mandate to honor agent guidance.
- [x] Token store: `AccountDAO` (M1) already covers this — encrypted-at-rest, Fernet from settings.
- [x] Defensive parsing of `result.content[0].text` / `structuredContent` envelopes — done, live-verified.
- [x] `MockInstamartClient` — rewritten to match the new interface (single-session-scoped, full-replace semantics, no `household_id`).
- [x] **Live-verified twice** against real Swiggy (`scripts/verify_mcp_client.py`, run inside docker w/ published OAuth callback port): real `get_addresses`/`search_products`/`get_cart` calls succeeded; `AccountDAO` encrypt→store→decrypt round-trip with a **real token** succeeded, and that decrypted token drove a second live call (10 addresses) — the M1↔M2 seam proven with real data, not mocked.
- [x] `refresh_token` obtainability — **RESOLVED: confirmed absent** (`refresh_token present: False`, keys always `access_token, token_type, expires_in, user_id, tid`). Falls back to re-consent, per `DB_DESIGN.md`.
- [ ] **Known, expected breakage:** `cart/service.py` / `whatsapp/router.py` (+ their legacy tests) still reference the old interface shape — fixed by M3, not before.
- [ ] **Still unverified:** `get_cart`'s per-item field name (`spinId` vs `itemId`) — both live runs hit an empty cart, so no item row has been inspected yet.

## Foundation — DB / DAO / config

- [x] Docker + docker-compose (SQLite on a mounted volume), `pytest` test container — verified building
- [x] `IDAO[T]` base (`app/core/dao.py`) — sync, per the locked concurrency decision
- [x] `Account` model + `AccountDAO` (`app/accounts/`) — template: one `Base`-only entity class (no `@dataclass`), `IAccountDAO(IDAO[Account])` + `AccountDAO(IAccountDAO)` in one file, `Fernet` injected via constructor, encrypt-on-write/decrypt-on-read. App-based folder structure locked (`accounts/`, `groups/`, `cart/`, `invites/` as entity-backed "apps"; `instamart/`, `whatsapp/`, `agent/`, `routers/` as integration-shaped top-level packages; `core/` for shared `Base`/`IDAO`).
- [x] `GroupDAO`+`GroupAccountDAO` (`app/groups/`), `ItemCartDAO` (`app/cart/`), `InviteTokenDAO` (`app/invites/`) — composite-PK entities use `"{key1}:{key2}"` for the generic `get_by_id`/`update`/`delete`, real domain methods (`get_by_group`, `get_holder`, `delete_all_for_group`, etc.) for actual call sites. `PRAGMA foreign_keys=ON` added to SQLite (`core/db.py`) now that real FK relationships exist.
- [x] `pydantic-settings` config object (`app/settings.py`)
- [x] FastAPI app skeleton: `app/main.py` (+ `/health`) + `app/dependencies.py` (DB session + all 5 DAOs + Fernet, wired via `Depends`). `app/routers/` still empty — real router modules land at M4.
- [x] All new DAO tests are native pytest (fixtures + `assert`, shared setup in `tests/conftest.py`); legacy `unittest.TestCase` files stay as-is per `IMPLEMENTATION_PLAN.md` §15. **52/52 tests green** (verified via `docker compose run test`).

**M1 complete.**

## Step 3 — Rewire `CartService` → `InstamartClient` — DONE

- [x] `CartService` rebuilt as the guard: `add`/`remove` take an already-resolved `spin_id` (search moved to the agent, M5) + `requested_by`; `NOT_FOUND`/`UNAVAILABLE` statuses dropped since they're the agent's concern now (`ProductVariation.available`), not the guard's.
- [x] Guard builds the `update_cart` **full-replace payload from local `ItemCart`** (`ItemCartDAO.get_by_group`) on every add/remove; `clear_cart()` called instead of an empty `update_cart` when the last item is removed, per `DB_DESIGN.md`.
- [x] Attribution = message sender, read straight off `ItemCart.requested_by` — no diff, no LLM.
- [x] Dedup: checked against the **local** `ItemCart` table (not live `get_cart`), so it stays correct even if Swiggy's cart expired.
- [x] Per-group `threading.Lock` serializes read-modify-write (SQLite alone doesn't cover the window between the local write and the remote `update_cart` call).
- [x] `items()`/`total()` reconcile local rows with live `get_cart()` for name/price display, since `ItemCart` stores neither (per `DB_DESIGN.md`).
- [x] 19 tests rewritten in pytest style (`tests/cart/test_service.py`) — the concepts survive (dedup, attribution, isolation, full-replace, totals); the literal method signatures don't, since free-text search moved out of the guard entirely.
- [x] **Cleanup:** `app/whatsapp/router.py`/`demo_seed.py`/`types.py` (+ their test) deleted — confirmed fully obsolete (`Action`/`Intent` classify-then-dispatch is what the real agent replaces; `Household`/`Member` superseded by M1's real `Account`/`Group`), not just broken.
- [x] **68/68 tests green, zero collection errors** — first fully-green run since M2's interface redesign.

## Step 4 — The Agent — mostly DONE (M5)

- [x] Custom LangGraph `StateGraph` — tool-calling **LOOP**, 3 nodes (`agent`, `tools`, `ask_human`)
- [x] Agent binds the MCP tools; injected params (`address_id`/`group_id`/`requested_by`) invisible to the model
- [x] `interrupt` for variant pick and checkout confirm (address pick stays in M4 onboarding)
- [x] Deterministic write-guard wraps every cart write; rollback on failed remote sync
- [x] Swappable `ChatOpenAI`, `temperature=0`, SQLite checkpointer
- [x] Wired end to end and **proven live on real WhatsApp + real Swiggy**
- [ ] **Tune the system prompt** — `app/agent/prompt.py` is still the first draft
- [ ] Expand the "world says no" scenario list (§7) into prompt coverage: out-of-stock, not-serviceable, no-match, min-order, cart ≥ ₹1000, address-not-saved → V2

### Known gaps found during live testing (not yet fixed)

- [ ] **`ProfileName` is never captured**, so `Account.name` stays `NULL` for anyone who joins by invite — `DB_DESIGN.md` §1 says it should be read from the first inbound message. Attribution then falls back to the phone number, so the money shot reads *"added by +9198…"* instead of a name. **Visible on camera.**
- [ ] **Holder gets no notification when someone joins** via invite — only the joiner is greeted, so the invite appears to do nothing from the holder's side.
- [ ] **`broadcast` has no error isolation** — it's a plain loop over `send`, so one unreachable recipient (not joined to the sandbox) silently kills delivery for everyone after them in the list.
- [ ] **`to_pay` renders as `102.0`** rather than `102` — cosmetic float artefact in user-facing text.

## Step 5 — Webhook glue + broadcast — DONE (M4)

- [x] `/webhook` router (`app/routers/webhook.py`) — Twilio signature verification (`get_verified_twilio_form`, the one `async def` in the codebase, forced by Starlette's `Request.form()` having no sync API), fast-ack + `BackgroundTasks` dispatch to `OnboardingService.handle_message`.
- [x] `Messenger` interface (`app/whatsapp/messenger.py`) — `IMessenger.broadcast` is concrete-on-interface (pure delegation to `send`, same Template Method pattern as `IAccountDAO.get_by_phone`). `ConsoleMessenger` (dev/test, inspectable `.sent` list) + `TwilioMessenger` (real, via the official SDK) both implement it.
- [ ] Broadcast-after-cart-change wiring — deferred to M5, since there's no cart conversation to broadcast *from* until the agent exists.

## Step 5b — Invite / onboarding flow — DONE (M4)

- [x] Holder onboarding: OAuth PKCE (`app/instamart/oauth.py`, deferred at M2 for lack of a consumer, built now) → `/oauth/callback` → `get_addresses` → reply-with-a-number → `Group.address_id` stored. Address-selection-pending is **derived from DB state** (holder role + `address_id IS NULL`), not a session flag — survives `OnboardingService` being reconstructed per request.
- [x] `invite`: signed, single-use, expiring JWT (`app/invites/jwt_tokens.py` — generic `sign`/`verify`, also reused for the OAuth `state` param) encoding `group_id` + `token_id`, 24h expiry.
- [x] Member join: decode + verify → `InviteTokenDAO.is_consumed` check → `GroupAccount(role=MEMBER)` created → token inserted (row's mere existence = consumed) → greeted. Replay tested and rejected.
- [x] Dedup by phone: `AccountDAO.get_by_phone` check-then-create, both in OAuth completion and invite consumption.
- [x] **Security note, correctly handled**: the PKCE `code_verifier` never travels through the browser-visible `state` param (would defeat PKCE's actual protection against code interception) — it's kept in a process-wide in-memory store keyed by phone, injected via `dependencies.py`. Documented limitation: this is single-process-only (fine for V1's single-process deployment); multi-process would have to move it into the DB.
- [x] **95/95 tests green** (accounts, groups, cart, invites, instamart incl. new `oauth.py`, onboarding service — 11 tests covering OAuth completion/address-selection/invite-generate/join/replay-rejection, both routers via `TestClient` + dependency overrides, both `Messenger` impls).
- [ ] **Explicit scope boundary**: M4 has no message *understanding* — a known member with no pending onboarding state gets a placeholder ("cart assistant isn't wired in yet"). Real cart conversation over WhatsApp needs M5 (the agent).

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
- **Local dev is Docker-based** — run/test via `docker compose` (`docker compose run test`, `docker compose up app`), not a host venv/bare `python`/`pytest`.
