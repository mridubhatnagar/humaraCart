---
name: standards-review
description: Review changed or specified code against HumaraCart's engineering guidelines in CLAUDE.md — DRY/YAGNI/KISS, FastAPI best practices, OOP/OCP, the IDAO/DAO contract, and controller→service→DAO layer responsibilities. Use before merging, in PRs, or whenever asked to review code for convention adherence in this repo.
---

# Standards Review (HumaraCart)

Review code against this repo's own engineering conventions, not generic taste.
The source of truth is `CLAUDE.md`.

## Procedure

1. **Load the standards.** Read `CLAUDE.md` first — it defines the rules you are
   checking against. If it changed, the checklist below follows it, not the other
   way around.
2. **Determine scope.** Default to the working diff (`git diff` against the base
   branch / uncommitted changes). If the user named files or a PR, review those.
   State what you reviewed.
3. **Review against the checklist** (below), reading the surrounding code so a
   finding is judged in context, not in isolation.
4. **Verify before reporting.** Only report issues you can defend with a concrete
   failure or a clear rule violation. Discard anything speculative — no
   false-positive noise. Prefer a short list of real issues over a long list.
5. **Report**, ranked most-severe first, in the output format below. If the code
   is clean, say so plainly.

## Checklist (mapped to CLAUDE.md)

**Principles (§1)**
- DRY: duplicated logic/knowledge that should be extracted; redefined domain shapes.
- YAGNI: speculative abstraction, unused params/flags, features not in demo scope,
  extension points for changes that won't come.
- KISS: needless complexity, cleverness over clarity, extra layers that add nothing.

**FastAPI & layering (§2)**
- Business logic in a route handler (should be thin — parse, delegate, respond).
- HTTP edge not using `APIRouter` / domain logic inlined in handlers.
- Cross-cutting concerns not via `Depends` (globals, ad-hoc wiring).
- Untyped dicts crossing I/O boundaries instead of Pydantic models/settings.
- Blocking calls in `async` handlers without offloading.
- Hardcoded secrets/tokens instead of settings + environment.
- **Anemic pass-through service** — a service method that only forwards to a DAO
  (`return self._dao.get_by_id(x)`) with no decision/rule/coordination.
- Layer leak: controller calling a DAO directly, or DB/persistence code outside a DAO.

**OOP / OCP (§3)**
- Depending on a concrete implementation where an interface exists (not programming
  to abstractions).
- Constructing collaborators in-place instead of dependency injection.
- Extending behavior by editing core/working code rather than adding a new class
  behind an existing interface (OCP violation).
- Leaky encapsulation; large public surfaces; inheritance where composition fits.

**DAO / IDAO (§4)**
- A DAO that does not inherit `IDAO` / does not honor the standard CRUD contract.
- DAO methods as `@classmethod`/`@staticmethod` (forces a global connection, breaks DI).
- Non-`async` DAO methods for DB I/O.
- Business rules living in a DAO (DAOs are persistence-only).

**Correctness & safety (Testing / Non-negotiables)**
- LLM used in a correctness-critical path (dedup, attribution, broadcast) instead
  of deterministic tested code.
- Correctness-critical logic without unit tests against the interface/mocks.
- Any hardcoded credential or token.

## Output format

For each finding:

- **[severity]** `path/to/file.py:line` — one-line description
  - **Rule:** which CLAUDE.md principle it violates (§ and name)
  - **Why:** the concrete problem (a failure, or why it breaks the rule)
  - **Fix:** the smallest change that resolves it

Severities: **blocker** (must fix — correctness/security/clear rule break),
**major** (should fix — real design/convention violation), **minor** (worth
fixing), **nit** (optional/style). Rank blockers first.

Do not rewrite the code unless the user asks — report findings and suggested fixes.
End with a one-line verdict (e.g. "3 findings: 1 blocker, 2 minor" or "clean").
