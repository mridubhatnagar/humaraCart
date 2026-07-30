# Known Issues — Found During Live Rehearsal

Bugs surfaced by testing against the real Swiggy account and real WhatsApp
sandbox, not caught by the unit suite because they only appear with two real
household members interacting close together in time.

---

## Fixed: a pending question could be answered by the wrong person

**Symptom:** Priya searched "milk", got a numbered list of variants, and before
she replied, another household member's unrelated message arrived. The wrong
variant got added to the cart (a different pack size than either person
selected), and the item's `requested_by` attribution was wrong (Amul Masti Dahi
showed as "added by" a member who never added it).

**Root cause:** `AgentService._is_paused()` only checked whether the
household's LangGraph thread had *any* outstanding interrupt — not who it was
addressed to. `AgentState.pending_options` and `pending_confirmation` are
shared per household (thread_id = group_id, deliberately, so duplicate-catch
and broadcasts work across members). Any inbound message from *any* sender
while a question was outstanding got wrapped in `Command(resume=body)` and fed
in as if it were the answer to that question — regardless of who actually sent
it. `_resolve_choice()` then mapped that stray text onto the wrong option, and
`requested_by` (never updated on a resume) stayed pinned to whoever's message
originally asked the question.

**Fix:** `AgentState.requested_by` already survives untouched across a resume,
so it already records who a pending question was asked of. `AgentService`
now reads it via `_pending_for(config)` before deciding whether to resume:
if a different sender messages while someone else's question is outstanding,
that message is not treated as an answer — the sender is told to wait, and the
graph is never invoked. `app/agent/service.py`, tests in
`tests/agent/test_service.py`.

**Live consequence:** one real Swiggy order (`244304152138218`, ₹232, wrong
items) was created via checkout before this was caught — `paymentStatus` was
still `PENDING` (never paid), and both the local cart and the real Swiggy cart
were cleared afterward.

---

## Fixed: concurrent messages could race on the same household's LangGraph
## checkpoint

**Symptom:** Two inbound messages for the same household landing close enough
together produced `openai.BadRequestError: ... tool_calls' must be followed by
tool messages ...` in the app logs.

**Root cause:** The webhook fast-acks and hands the real work to
`BackgroundTasks`, which FastAPI runs on a thread pool — a pool of *concurrent*
workers, not a serial queue. Two messages for the same household can each get
their own thread and both call `agent.handle()` on the same `thread_id` at
once. One thread commits an assistant message with `tool_calls` as its own
checkpoint, then goes off to do a slow external MCP call before writing the
matching tool response. If a second thread reads the checkpoint in that gap and
tries to continue the conversation, OpenAI rejects the incomplete history —
this is a business-logic race (two valid reads building on the same
in-progress state), not a database consistency violation; ACID guarantees on
the SQLite writes are unaffected by it.

**Status:** Fixed. Initially accepted as a risk for V1 (self-healing — the
original, slower invocation finishes normally and the checkpoint ends up
consistent) with a plan to just pace messages during recording instead. Given
neither phone during the actual recording is fully under one person's control
(a second, independent tester holds one of them), pacing couldn't be
guaranteed, so it was fixed properly instead: `ConversationService` now holds
one process-wide `threading.Lock`, held around the `agent.handle(...)` call, so
two threads can never run an agent turn at the same time. `app/conversation/service.py`,
tests in `tests/conversation/test_service.py`. A queue-based redesign was
considered and rejected — strictly more moving parts (a persistent consumer,
lifecycle management, per-household partitioning) than a lock for the
identical single-process guarantee; queues earn their keep across multiple
processes/machines, which this app doesn't have.
