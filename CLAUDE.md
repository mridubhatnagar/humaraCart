# HumaraCart — Engineering Guidelines

WhatsApp-based shared household cart for Swiggy Instamart, built on Swiggy's
Instamart MCP. See `IMPLEMENTATION_PLAN.md` for scope, architecture, and decisions.

These are the conventions to follow for all code in this repo.

---

## 1. Software engineering principles

**DRY** — one source of truth for every piece of logic and knowledge.
- No copy-pasted logic; extract shared behavior into a function/class/dependency.
- Domain types (`Account`, `Group`, `Product`, …) are defined once and reused; do
  not redefine shapes ad hoc.

**YAGNI** — build only what V1 (the demo) needs.
- No speculative abstraction, config flags, or "we might need it later" code.
- Deferred features (invite/JWT, order tracking, V2 reorder intelligence) are NOT
  built until they're actually on the table. See the plan's In/Out scope.

**KISS** — the simplest thing that works.
- Prefer plain functions and small classes over frameworks-within-frameworks.
- Deterministic code for correctness-critical logic (dedup, attribution,
  broadcast); the LLM only where genuine intelligence is needed.
- Readable over clever. Match the style of surrounding code.

> When DRY and YAGNI/KISS conflict, do not abstract prematurely: two similar
> pieces of code are fine; extract on the third occurrence, not the second.

## 2. FastAPI best practices

- **Package layout** (per FastAPI "Bigger Applications"): HTTP edge in
  `app/routers/*` using `APIRouter`; app assembled in `app/main.py` via
  `include_router(...)`. Domain logic lives in sub-packages (`agent/`, `cart/`,
  `instamart/`, `whatsapp/`), never inline in route handlers.
- **Thin routers, fat services.** Route functions parse/validate the request,
  call a service, and shape the response — no business logic in the handler.
- **Layer responsibilities — keep them distinct:**
  - **Controller (router):** HTTP concerns only — parse, validate, delegate, respond.
  - **Service:** the business logic and orchestration — decisions, domain rules,
    coordinating ≥2 collaborators (e.g. `CartService`: dedup, `requested_by`
    attribution, ordering the MCP calls, deciding broadcasts).
  - **DAO:** persistence only — fetch/store entities, no rules.
  - **No anemic pass-through services.** A service method that is just
    `return self._dao.get_by_id(x)` shouldn't exist — either it's missing the
    logic that justifies it, or the layer isn't warranted (YAGNI). A service earns
    its place with a decision, a rule, or coordination — not by wrapping a DAO.
- **Dependencies for cross-cutting concerns** (`app/dependencies.py`): Twilio
  signature verification, resolving member↔household from the inbound number,
  injecting shared singletons. Use `Depends(...)`; don't reach for globals.
- **Pydantic for all I/O boundaries** — request/response models and settings
  (`pydantic-settings`); no untyped dicts crossing boundaries.
- **Default to sync `def` handlers — do not reach for async.** FastAPI threadpools
  `def` handlers, which covers our concurrency many times over; async's only real
  benefit (huge I/O concurrency on one thread) is irrelevant at this scale. Keep it
  all sync: sync OpenAI, sync SQLAlchemy/SQLite, sync Twilio, our own sync MCP
  client. Scale later via threadpool size → more workers/replicas → a task queue,
  none of which is async. Revisit async only if wiring the MCP client forces it —
  and even then it's a mechanical change behind the interfaces, not a redesign.
- **Config via settings object + environment**, never hardcoded secrets/tokens.

## 3. Object-oriented programming

- **Open for extension, closed for modification (OCP).** Design classes so new
  behavior arrives as a *new class implementing an existing interface*, not by
  editing working code. New Instamart backend → new `InstamartClient` impl; new
  storage → new `Repository` impl; new capability → new agent tool; new channel →
  new class behind a messaging interface — in every case the existing core is
  untouched. Put these extension points at seams that *actually change* (backend,
  persistence, channel, tools); per YAGNI, don't invent extension points for
  changes that won't come.
- Model behavior as cohesive classes with clear responsibilities
  (`CartService`, `Broadcaster`, `InstamartClient`, `<X>Repository`).
- **Program to interfaces (abstractions), not implementations.** The
  `InstamartClient` ABC is the canonical example: `CartService` depends on the
  interface; `McpInstamartClient` (real MCP) and `MockInstamartClient` (test
  double) implement it. Swapping backends changes one wiring line.
- **Dependency injection over construction-in-place** — pass collaborators in
  (constructor args / FastAPI `Depends`); don't `new` them deep in the code. This
  keeps units testable in isolation.
- Encapsulate state; keep public surfaces small; prefer composition over
  inheritance.

## 4. Database interaction

- **All persistence goes through a dedicated DAO class.** No raw queries, ORM
  sessions, or connection handling in routers, services, or the agent — they
  depend on a DAO *interface*, never on the DB directly.
- **Use SQLAlchemy (ORM) for all persistence — no direct/raw SQL, anywhere.** Even
  inside a DAO, express reads and writes through SQLAlchemy's ORM/query API — never
  raw SQL strings or `session.execute(text("SELECT ..."))`. This is what keeps the
  backend swappable by connection URL (SQLite → Postgres) and the DAOs testable.
- **Every DAO inherits the common `IDAO` base interface**, which defines the
  standard CRUD contract so all DAOs share one shape (DRY). `IDAO` is generic
  over the entity type:

  ```python
  T = TypeVar("T")

  class IDAO(ABC, Generic[T]):
      @abstractmethod
      async def create(self, entity: T) -> T: ...
      @abstractmethod
      async def get_by_id(self, id: str) -> T | None: ...
      @abstractmethod
      async def update(self, entity: T) -> T: ...
      @abstractmethod
      async def delete(self, id: str) -> None: ...
  ```

- **Concrete DAOs bind the entity and add only domain-specific queries** (OCP —
  extend, don't modify the base):

  ```python
  class AccountDAO(IDAO[Account]):
      async def get_by_phone(self, phone: str) -> Account | None: ...
  ```

- **Never put the storage technology in a class name.** The concrete DAO is
  `AccountDAO` — named for the entity it serves, not the database. Which backend
  stores it is a **connection-URL / config detail**, so SQLite→Postgres is a config
  change, NOT a new `SqliteAccountDAO` / `PostgresAccountDAO` class. Use an
  engine that switches by URL (SQLAlchemy) so one `AccountDAO` serves both.
  (The lone exception is a **test double** like `InMemoryAccountDAO` — a testing
  artifact, not a production storage choice.)
- **Instance methods on an injected DAO** — never `@classmethod`/static, which
  would force a global connection and break DI. (Whether they are `async` follows
  the handler/stack choice in §2, not the database itself.)
- **Call chain:** controller → service → DAO → DB. Controllers never call a DAO
  directly.
- **V1 uses SQLite** via per-entity DAOs (`AccountDAO`, `GroupDAO`, …) behind
  `IDAO`; full schema in `DB_DESIGN.md`. The demo household is created through the
  onboarding flow (holder OAuth → invite → member joins), not seeded. The backend
  is a connection-URL detail via SQLAlchemy, so moving to Postgres later changes
  config — not the class names, not the callers.

---

## Testing

- Correctness-critical logic (cart engine, dedup, attribution, broadcast) must be
  unit-tested against the interface using the in-memory/mock implementations —
  fast, no network or external login required.
- Tests live in `tests/`, run with **`pytest`** (or `docker compose run test`).
  Pytest also runs any legacy `unittest.TestCase` classes as-is.

## Non-negotiables

- Never hardcode credentials/tokens; load from environment.
- Keep the LLM out of correctness-critical paths — it decides intent and phrases
  replies; tested code guarantees cart correctness.
- **Strictly no banner-style comments, anywhere.** Never add decorative separators
  such as `# ====== Cart Service ======`, `##########  helpers  ##########`, or
  `# ----- routes -----`. They are visual noise, not information. Use a plain
  one-line comment only when it explains *why* something non-obvious is done; let
  clear names and function/class boundaries do all the sectioning.
- **No `Co-Authored-By` / `Claude-Session` trailers on commits.** Do not append
  the default Claude Code attribution lines to commit messages in this repo —
  commit as the configured git author only.
- **Adhere to Swiggy's MCP agent guidance** (verbatim + links in `REFERENCE.md`);
  follow the instructions Swiggy injects in tool-response `message` fields, and use
  those messages as-is (their branding). **Consult the authoritative docs** when
  writing MCP code — index `https://mcp.swiggy.com/builders/llms.txt`; append **`.md`**
  to any doc URL for the verbatim source (don't trust summaries). For **`checkout`
  specifically**:
  - cart total **must be `< ₹1,000`** — check `get_cart`'s bill first; if over, tell
    the user to use the Swiggy app (do not attempt checkout).
  - **always get explicit user confirmation** (state the delivery address) before placing.
  - payment methods come from **`get_payment_options`** — never fabricated.
