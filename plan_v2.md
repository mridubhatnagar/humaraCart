# HumaraCart — V2 Plan (Real Usage, Post-Demo)

> Scope of this document: moving past the V1 recorded demo (see
> `IMPLEMENTATION_PLAN.md`) toward real usage — at minimum, the Swiggy team
> should be able to use HumaraCart for real. Not scoped to public/arbitrary
> scale; exact user count is unknown.

---

## 1. Status

- Swiggy has granted **production access** directly (no staging track offered
  or needed) — confirmed by email: *"Your integration for humaraCart is now
  live. Your redirect URI has been whitelisted on the Swiggy MCP gateway."*
- Production OAuth redirect URI whitelisted: `https://humaracart.mridulabs.dev/oauth/callback`.
- Nothing on the Swiggy MCP side blocks V2 — local dev already ran against the
  same real production MCP (`mcp.swiggy.com`) that this now formalizes.
- Two things from Swiggy's email to honor going forward:
  - Tell Swiggy before shipping any new/changed redirect URI (an unwhitelisted
    one fails auth outright).
  - Treat every MCP tool response as fresh state — don't cache
    availability/pricing/menus.

---

## 2. Open Items (from planning discussion)

| # | Item | Status |
|---|---|---|
| 1 | Concurrent messages to the agent | **Decided** — see §2.1 |
| 2 | Move off `localhost` to real hosting | **Decided** — see §3 |
| 3 | Move WhatsApp out of the Twilio sandbox | **Registration done** — see §2.2 |

### 2.1 Concurrent messages (decided)

Current state (V1): two in-process `threading.Lock`s —
`ConversationService._agent_lock` (global, serializes every household's every
agent turn) and `CartService._locks` (per-group, for the cart
read-modify-write window). Both are correct only within a single process.

Why an explicit lock is needed at all — the critical section spans external
calls (Swiggy's `update_cart`, which is full-replace with no version/ETag
param, and the OpenAI LLM calls reading/writing the LangGraph checkpoint), so
it can't be made atomic by a database transaction alone; nothing on Swiggy's
side supports optimistic compare-and-swap, so pessimistic exclusion is the
only option.

**Decision: replace both `threading.Lock`s with a Postgres advisory lock**
(`pg_advisory_xact_lock(hash(group_id))`), held for the duration of the
agent turn / cart update.

- Reuses infra already committed to (Postgres is going in for entity data +
  the checkpointer anyway) — no new service to run.
- Correct today (single EC2 process) and stays correct automatically if the
  app is ever scaled to more than one process/container — no future
  migration needed, unlike an in-process lock fix.
- Considered and rejected:
  - **Celery + Redis** — solves work *distribution* across processes, not
    mutual exclusion; would still need a lock layered on top, so it adds a
    whole new stack (Redis + Celery workers + monitoring) to arrive at a
    guarantee Postgres already gives for free. Also skips rungs on the
    project's own scaling ladder (threadpool size → more workers/replicas →
    a task queue) before any of them are actually exhausted.
  - **Redis-only lock** (no Celery) — works, and is a legitimate production
    pattern, but is new infra with only this one use, and needs a TTL/lease
    sized correctly (too short → lock expires mid-turn and the race
    reappears; too long → a crashed process blocks a household
    indefinitely). A Postgres advisory lock has no TTL to tune — it's tied
    to the DB session/transaction and releases automatically on disconnect.
  - **Per-group in-process lock only** (no DB) — cheaper short-term, but
    would need replacing again the moment the app scales beyond one process;
    the advisory lock costs about the same effort now and doesn't need
    revisiting later.
- Also flagged (not yet addressed): the OAuth PKCE `code_verifier` store
  (`app/dependencies.py`) is in-memory and single-process-only (see
  `TODO.md`) — same category of problem, same candidate fix.

**Update 2026-09-02: implemented, with one deliberate deviation from "both
locks" above.** `app/core/locks.py` adds `IGroupLock` (`PostgresGroupLock` —
real, `pg_advisory_xact_lock(hashtext(group_id))` on a dedicated session held
open for the `with` block; `InMemoryGroupLock` — test double, a per-group
`threading.Lock`, same shape as the old code). Uses Postgres's own
`hashtext()`, not Python's `hash()` — `str` hashing is salted per-process
(`PYTHONHASHSEED`), so two workers would compute different keys for the same
group_id and the lock would silently stop excluding anything.

`ConversationService` now takes `group_lock: IGroupLock` and holds it for the
whole turn (`with self._group_lock.acquire(group.group_id):`), keyed per
group instead of the old single process-wide lock — unrelated households no
longer block each other.

`CartService`'s own lock was **removed rather than converted**: its
`add`/`remove` are reachable only through `app/agent/tools.py`, which only
runs inside an agent turn — i.e. already inside `ConversationService`'s held
lock. Postgres advisory locks are per-*session*, not per-thread like
`threading.Lock` was — acquiring the same `group_id` key again from a second
DB session nested in the same call stack would block waiting on the first
session's own still-open transaction, deadlocking the request. Converting
both sites literally (as first written above) would have shipped that bug.
Verified live against real Postgres: same-group calls serialize, different
groups run concurrently, no deadlock.

All 180 tests pass unchanged in shape (only the two `ConversationService`
construction sites in `tests/conversation/test_service.py` gained
`group_lock=InMemoryGroupLock()`).

**Demo plan (before/after, for video):** the race is real even within a
single process — FastAPI's sync handlers run on a threadpool, and the
critical section (LLM call + Swiggy MCP `update_cart` round trip) spans
several real seconds, so two real people are enough to trigger it without a
script.

- **Before**: with the lock removed, both household test numbers (holder +
  member) send an item (e.g. "add milk") within ~1-3 seconds of each other
  (countdown-coordinated). Expect a lost update — the cart ends up short an
  item.
- **After**: same setup with the Postgres advisory lock in place, same
  countdown-send. Cart should correctly show both items.
- Both phones screen-recorded simultaneously (same approach as the V1 demo)
  and placed side by side in the edit.
- Now that WhatsApp is off the sandbox (see §2.2), retakes are cheap — Tier 0
  gives 250 business-initiated conversations/24h (not shared with other
  Twilio users), and replies don't count against it. No more "budget ~1 take
  per day" constraint like the old sandbox cap.
- Filmed only once both the concurrency fix and hosting (§3) are actually
  built — "before" needs the lock genuinely absent, "after" needs the real
  Postgres advisory lock, not a placeholder; and the webhook needs to be
  live for real WhatsApp round trips to work at all.

### 2.2 WhatsApp out of sandbox (registration done)

**Update 2026-08-31: steps 1-3 below are done.** Twilio account upgraded to
paid, number `+16169844038` purchased, Meta Business Manager created
(sole-proprietor), WhatsApp Sender registered under Self Sign-up with display
name "HumaraCart" — see [[twilio-whatsapp-number]] in memory. Sender is
online.

**Still pending: step 4** — pointing the webhook (and `OAUTH_REDIRECT_URI`)
at the hosted app. Blocked on §3 (real hosting) actually being live; this
number cannot be handed to Swiggy until that's done, since nothing would
answer its messages yet.

Replaces the shared Twilio Sandbox (50 msgs/day, shared across all sandbox
users, join-code friction) with a real production WhatsApp sender.

**Decision: Twilio Self Sign-up → Tier 0** (no full Meta Business
Verification needed to start):
1. Buy a Twilio number (virtual/cloud, no SIM needed).
2. Create a Meta Business Manager account — sole-proprietor/unregistered is
   fine (personal Facebook account, business name, email, address; no legal
   entity required).
3. Twilio Self Sign-up registers that number as a WhatsApp Sender (SMS/voice
   OTP verification on the number).
4. Point the webhook (and `OAUTH_REDIRECT_URI` if desired) at the now-hosted
   app (§3).

Lands on **Tier 0 automatically: 250 unique business-initiated conversations
per 24h.** Replies to a user-initiated message do **not** count against this
— only unprompted app-initiated messages do. Given HumaraCart's flow is
almost entirely replies, this is generous headroom versus the sandbox's
shared 50/day.

Was previously blocked on the hosting decision (§3) — now unblocked since
hosting is decided.

- Considered and rejected:
  - **Full Meta Business Verification** — unlocks higher tiers (1K → 10K →
    100K → unlimited), but real legal-entity paperwork, slow/case-by-case
    for an unregistered business. Not worth it for a test-and-possibly-sunset
    scope that won't hit 250/day.
  - **Switching BSP** (MessageBird, Vonage, 360dialog, Gupshup, or Meta's
    Cloud API direct) — every BSP sits on the same underlying Meta WhatsApp
    Business Platform; the Tier 0 cap is set by Meta, not the BSP. Switching
    wouldn't raise the limit, would just mean rewriting `IMessenger` for a
    new provider with no upside.
  - **Asking Twilio to raise the sandbox cap directly** — long shot; the
    sandbox number is shared globally across all trial developers, unlikely
    to be raised per-account.
  - **Dropping WhatsApp as the channel** — ruled out by the project's own
    premise (IMPLEMENTATION_PLAN.md: "real WhatsApp is the core of the
    pitch").

**Cost (verified against Twilio's pricing):** $0.005/message from Twilio
(in or out); Meta charges nothing for free-form replies within the 24h
customer service window (almost all of HumaraCart's traffic), ~$0.0034/
message for business-initiated utility/auth templates outside it. Cents at
real-usage volume, not a real cost concern for this scope.

**Timeline:** Self Sign-up registration itself is near-instant (a few
minutes) — this is what Tier 0 needs. The multi-week timeline sometimes
quoted for WhatsApp is **full Meta Business Verification only**, which this
plan deliberately does not pursue (see rejected alternatives above).

**Separate gotcha, not sandbox-related:** while the Twilio account is still
in **Trial** status (no payment method added), Twilio restricts messaging to
only pre-verified phone numbers (max 5/account) — this applies regardless of
WhatsApp Sender registration. The account must be **upgraded to paid**
before arbitrary real users can message and use the bot.

Note: as with §2.1, this is not yet implemented — decision recorded for
when it's picked up.

---

## 3. Real Hosting (decided)

| Decision | Choice |
|---|---|
| Cloud | **AWS** (existing credits) |
| Compute | **Single EC2 instance** running the same `docker compose` stack as local — no ECS/Fargate, no load balancer, no auto-scaling (not warranted at this scale) |
| Instance size | **`t3.micro`** (1 GiB RAM) — measured idle baseline via `docker stats` is ~183 MiB total (`app` 152 MiB, `postgres` 31 MiB); the app is I/O-bound on OpenAI/Swiggy calls, not local compute, so this doesn't grow much under load. Free-tier eligible; usage is low (Swiggy team only). Resizable later if traffic ever justifies it. |
| Database | **Self-hosted PostgreSQL** as a container in the same compose stack — **not RDS** |
| Persistence | **Single 30 GB gp3 EBS volume** (root — matches the free-tier allowance), `DeleteOnTermination` **unchecked** so a future instance replacement doesn't wipe the Postgres data directory along with the OS |
| Domain | `https://humaracart.mridulabs.dev` (already whitelisted with Swiggy) → DNS pointed at the EC2 instance |

### 3.1 Database migration scope

Both move to Postgres:
- **Entity data** (`AccountDAO`, `GroupDAO`, cart, invites, …) — trivial: all
  persistence already goes through SQLAlchemy behind `IDAO`, so this is a
  `database_url` config change plus a Postgres driver dependency. No class or
  caller changes (per CLAUDE.md's DAO design).
- **Agent checkpointer** (`app/agent/factory.py:26`, `make_checkpointer`) —
  **not** a trivial swap. It currently bypasses SQLAlchemy entirely: a raw
  `sqlite3.connect()` wrapped in LangGraph's `SqliteSaver`
  (`langgraph.checkpoint.sqlite`). Moving this to Postgres needs the separate
  `langgraph-checkpoint-postgres` package (`PostgresSaver`) and a different
  connection/setup call — isolated to this one function, but real work, not
  config.

### 3.2 Status

**Update 2026-09-01: code side is done.**
- `requirements.txt` — swapped `langgraph-checkpoint-sqlite` for
  `langgraph-checkpoint-postgres` + `psycopg[binary]` (one driver, used by
  both SQLAlchemy's `postgresql+psycopg://` dialect and the checkpointer).
- `app/agent/factory.py` — `make_checkpointer` now opens a `psycopg`
  connection and wraps it in `PostgresSaver`, calling `.setup()` once
  (idempotent, same pattern as `create_all` in `main.py`). Entity DAOs needed
  no changes — already backend-agnostic via SQLAlchemy (`app/core/db.py`).
- `.env.example` — added `DATABASE_URL`, `POSTGRES_USER`, `POSTGRES_PASSWORD`,
  `POSTGRES_DB` templates; `DATABASE_URL` must reference the same
  user/password/db as the `POSTGRES_*` vars.
- Tests untouched and still fast/network-free: no test exercises
  `make_checkpointer` (graph tests use `MemorySaver`), and the `test` compose
  service stays on in-memory SQLite for entity DAOs.

**Update 2026-09-01: migration complete and verified.** `docker-compose.yml`
now has a `postgres` service (`env_file: .env.local`, `pgdata` volume,
healthcheck) with `app` depending on it healthy; `app`'s `DATABASE_URL` comes
from `.env.local` rather than being hardcoded. `.env.local` has
`DATABASE_URL`/`POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` set (dummy
dev values — container is not exposed outside the compose network).

Smoke-tested: `docker compose up` brings up Postgres (healthy) + app cleanly;
`create_all` and `PostgresSaver.setup()` both ran against it —
`accounts`/`groups`/`item_carts`/… and `checkpoints`/`checkpoint_blobs`/
`checkpoint_writes`/`checkpoint_migrations` all present in one DB, confirmed
via `\dt`. Full test suite (180 tests) passes unchanged.

Next after this: the concurrency fix (§2.1 — swap both `threading.Lock`s for
`pg_advisory_xact_lock`), then actual EC2 deployment (§3).
