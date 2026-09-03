# scarlet-agentic-harness

A generalized decentralized agentic **Skill** harness built on top of
[scarlet-composer-studio](https://github.com/disys-lab/scarlet-composer-studio)'s
`scarlets` primitives (`Mapper`, `Federator`, `Messenger`) — deployed
alongside [Gustavo](https://github.com/disys-lab/gustavo), though nothing
here is deployed yet (see Status below).

## What this is

Scarlet Composer Studio gives agents shared memory and messaging over Redis.
It does not define what an agent's *task* looks like — that's what this
repo adds: a **Skill** interface (`scarlet_agentic_harness/skills/base.py`)
that any well-defined distributed computation implements, plus a thin,
skill-agnostic harness that dispatches invocations across a head and any
number of worker agents using only scarlets primitives — no side channels.

Three skills exist so far, deliberately chosen to exercise different shapes:

- **`median`** — workers each hold a private, unordered list of numbers; the
  head assigns one worker as coordinator (workers never self-assign — see
  `scarlet_composer_agentic_design/DESIGN_v3.md` §8.5); the coordinator
  gathers every worker's sorted local partition via `Mapper.AllGather()` and
  merges them into the true global median. Median isn't an associative
  reduction (you can't combine two workers' local medians into the global
  one), so it can't be built on `Federator` at all — it needs the full
  partitioned data and a real merge.
- **`sum`** — the first `Federator`-backed skill, and the first to take a
  parameter (`transform: identity|square`). `Federator` *is* built for
  associative reductions, but the coordinator is still a randomly-assigned
  worker, same as median — nothing about `Federator` requires centralizing
  on the head (see the coordinator-default discussion). Reports both the
  total and `n` (total element count across all workers, co-aggregated as
  one numpy array in a single `Aggregate()` call, not `len(workers)` — those
  are different numbers, and conflating them was a real bug caught while
  building this). `sum(transform=identity)` and `sum(transform=square)`,
  plus `n`, are enough to derive mean/variance/stddev from pure arithmetic
  with no new skill and no new distributed protocol —
  `tests/test_sum_skill.py` proves this concretely, deriving a real variance
  from two real `sum` invocations and checking it against
  `statistics.pvariance`.
- **`combine`** — the local, non-distributed arithmetic step that closes the
  composition loop: it evaluates a model-supplied expression (e.g.
  `"s2/n - (s1/n)**2"`) against model-supplied named variables (e.g. the
  `result`/`n` from two `sum` calls) via `safe_eval` (an AST-whitelisted
  evaluator under `skills/safe_eval.py` — numeric constants, variable
  lookup, `+ - * / **`, unary `+/-` only; everything else, including any
  function call or attribute access, is rejected before anything runs).
  Deliberately generic rather than a `CombineVarianceSkill` with the formula
  baked in — an earlier design considered that and it defeats the whole
  point of a small composable skill library. `contribute()` is a no-op (no
  per-worker data to gather); `coordinate()` runs on one randomly-chosen
  worker, same "head never computes" rule as median/sum, and needs no
  readiness handshake since it depends on nothing from peers.
  `tests/test_variance_composition_end_to_end.py` chains two real `sum`
  calls into one real `combine` call and checks the result against
  `statistics.pvariance` — the *system* composing sum→combine into variance,
  not just the underlying data being composable in principle (which
  `test_sum_skill.py` already showed by hand).

Together these prove the `Skill` interface generalizes past "head
aggregates centrally", past "every skill needs `Mapper`", and past "every
skill is distributed" — a new skill is a new module under `skills/`, never
a change to `head.py`/`worker.py`'s dispatch logic.

## Status

**Built and locally verified. Not deployed anywhere.**

- ✅ `Skill` interface (step 1)
- ✅ `MedianSkill` reference implementation (step 2)
- ✅ Thin harness: two-channel bus setup, capability reporting/discovery,
  generic dispatch (`head.run_skill`), worker-side message dispatch
  (`worker.handle_message`) (step 3)
- ✅ End-to-end verified locally: 3 real worker **subprocesses** + a head,
  against a disposable local Redis, using the real `Messenger`/`Mapper`
  primitives and the actual `__main__.py` entrypoint — not a shortcut that
  calls skill methods directly. See `tests/test_median_skill.py`.
- ✅ **The head's LLM tool-calling loop (`head.converse`)** — turns a
  human's free-text message into zero or more skill invocations plus a
  final natural-language reply, handling multiple tool calls in one turn
  (needed for composition, e.g. variance-via-two-sum-calls) and a
  `max_turns` safety limit. Tested two ways: pure control-flow tests with
  `head.run_skill` monkeypatched (`tests/test_head_converse.py` — no Redis),
  and a full end-to-end test where a scripted fake LLM's tool-call decision
  drives the *real* distributed median computation across 3 real worker
  subprocesses and real Redis (`tests/test_converse_end_to_end.py`). Only
  the "which tool to call" *decision* is faked anywhere in this codebase —
  everything downstream of that decision is real.
- ✅ **`LLMClient`'s wire-format translation** (canonical message shape ↔
  the real OpenAI SDK's shape) is unit-tested against a mocked `openai`
  client object (`tests/test_llm_client.py`) — **and now also verified
  against a real live backend** (Claude Sonnet 4.6, via Anthropic's
  OpenAI-SDK-compatibility endpoint — see the real-LLM validation entry
  further down) with zero code changes needed. `__main__.py`'s head role
  uses `LLMClient` + `converse()` for real whenever `LLM_BASE_URL` is set.
- ✅ **`sum` skill** — `Federator`-backed, parameterized (`transform`),
  reports total element count `n` correctly (co-aggregated with the sum, not
  `len(workers)`). End-to-end tested for both transforms plus a real
  variance derived from two `sum` calls (`tests/test_sum_skill.py`).
- ✅ **`combine` skill** — generic expression+variables evaluator
  (`safe_eval`, AST-whitelisted), runs on a randomly-chosen worker, no
  readiness handshake needed. `tests/test_variance_composition_end_to_end.py`
  chains two real `sum` calls into a real `combine` call and checks the
  result against `statistics.pvariance` — the system now composes
  sum→combine automatically via `run_skill`, not just by hand in a test.
- Still missing: `converse()` itself deciding to make two `sum` calls and a
  `combine` call in sequence for a human's variance question — the pieces
  it would chain together are now real and tested, but nothing has driven
  that chain through the LLM tool-calling loop yet (only `head.run_skill()`
  called directly, three times, in the composition test above).
- ✅ **Auditability** — `converse()` now returns a `ConverseResult`
  (`answer` + the full canonical-shape `messages` transcript), not a bare
  string, and takes an optional `on_event` callback fired synchronously for
  narration, tool calls, tool results, and the final answer as they happen.
  Previously a turn's own narration ("I'll call X because...") was silently
  discarded the moment that turn *also* contained a tool call — only the
  bare final string, or nothing, ever survived. `tests/test_head_converse.py`
  covers both the retained transcript and the event sequence/ordering.
  `ConversationDidNotConclude` also now carries the partial transcript for
  post-mortem. `__main__.py`'s LLM-backed chat mode logs every event to
  stderr as JSON as a real (if minimal) live audit trail.
- ✅ **Worker-level concurrency** — a worker no longer blocks its whole
  dispatch loop inside one `skill.coordinate()` call while it runs (this was
  a named, explicit limitation before). Fixed via `router.py`'s
  `MessageRouter`: exactly one background thread owns a bus's `Receive()`
  (scarlets' `Messenger` is a strict per-agent FIFO with unconditional
  ack-on-read and no peek/filter — confirmed by reading the installed
  package's source — so two independent callers of `Receive()` on the same
  bus can and will silently steal messages meant for each other; this is
  exactly why naive thread-per-message dispatch would have been unsafe
  without a demultiplexing layer in front). The router demultiplexes by
  `request_id` into per-request queues; unmatched (unsolicited) messages go
  to a `default_handler`, which is how `worker.start_dispatch()` now spawns
  a thread per incoming `skill_contribute`/`skill_coordinate` instead of
  looping. `tests/test_worker_concurrency.py` forces two different skill
  invocations onto the *same* coordinator concurrently and asserts both
  return fully correct results — the actual risk being tested is message
  cross-talk/loss between the two, not just raw non-blocking speed.
- ✅ **Retry on transient mid-computation failure** — `run_skill()` now
  retries (fresh `request_id`, fresh worker survey, possibly a new
  coordinator) when a result is marked `"retryable": True` — set by
  median/sum for failures that are plausibly transient (a contributor never
  signaled ready, an `AllGather`/`Aggregate` call failed, the coordinator
  never replied at all). `combine`'s logical errors (bad expression) are
  explicitly `"retryable": False` — retrying those would just reproduce the
  same error. A skill that doesn't set the flag defaults to *not*
  retryable, the conservative choice. This also required teaching
  `Buses.gather_workers()` a staleness filter (`max_staleness`, default
  60s): scarlets' own registry entries never expire on their own (confirmed
  by reading `Messenger.Register()`/`ReportStatus()` — a plain `r.set()`,
  no TTL; only the 30s heartbeat keeps a live agent's timestamp moving), so
  without this filter a genuinely dead worker's stale record would be
  retried against forever instead of ever being excluded.
  `tests/test_run_skill_retry.py` drives this deterministically (a fake
  worker impersonated via raw Messenger traffic in the test process, not a
  real subprocess kill, so the test controls exactly which attempt
  succeeds) — one test proves recovery after one bad attempt, the other
  proves it still gives up cleanly once every attempt fails.
- Known, accepted gap in the retry story: excluding a genuinely-dead worker
  from a retry relies entirely on the new staleness filter, since scarlets'
  registry has no TTL of its own — a worker that dies and is replaced by a
  fresh one *reporting under the same agent_id* within the staleness window
  would not be distinguished from the original. Not addressed here; would
  need an upstream change to scarlets' own registry semantics (instance
  IDs are already tracked internally — see `Messenger._instanceId` — just
  not surfaced through `GatherStatus()` today).
- ✅ **`run_skill()`/`converse()` are now fully async — dispatch-and-return,
  never block-and-wait.** This was a full rewrite, not an extension: both
  functions' calling convention changed from returning a value to firing a
  callback (`on_result`/`on_done`) on some later thread, once. Built on top
  of three foundational, independently-unit-tested pieces added first
  (`router.py`'s `on_key()` non-blocking registration, `timeout_watcher.py`'s
  single shared deadline-scanning thread instead of one thread per pending
  wait, and `conversation_store.py`'s thread-safe state — needed because no
  single thread's stack spans a conversation anymore once waiting is
  callback-based; each leg of it runs on a different, short-lived thread).
  Retry is a chain of callbacks now, not a loop. `converse()`'s tool calls
  within one turn dispatch *concurrently* (a real behavior change, not just
  a mechanical port — nothing requires waiting for call 1's reply before
  starting call 2 once dispatch is non-blocking), and rejoin in the
  model's original call order regardless of completion order (`_Joiner`),
  not first-finished order. `tests/helpers.py`'s `run_skill_sync()`/
  `converse_sync()` give tests (and `__main__.py`'s interactive CLI) a way
  to block on one specific call's result via a `threading.Event` — legitimate
  local blocking to drive a synchronous caller, not blocking inside the
  library's own logic. All 8 tests that called the old synchronous
  `run_skill()`/`converse()` directly were rewritten against the new
  callback contract, not left broken; 58 tests total, stable across
  repeated runs.
- ✅ **`AgentDialogue` (`dialogue.py`)** — generalized agent-to-agent
  natural-language conversation, riding the same buses as everything else.
  One generic message envelope (`agent_message`: `conversation_id` +
  free-form `content`), not a new fixed-schema type per use case — a
  status-check protocol with rigid fields would reduce the model to
  filling in a form, not reasoning. Not built on `router.py`'s `on_key()`:
  an incoming `agent_message` can be either a reply to a conversation this
  agent started or a brand-new one someone else started, and only the
  message reveals which — `AgentDialogue` keeps its own small
  `conversation_id -> handler` registry, fed by a bus's `default_handler`
  (the same integration point `worker.start_dispatch()` already uses for
  skill dispatch), rather than the router's key-matching, which can't
  express "keyed, but fall through if nobody's waiting" without weakening
  the guarantee `skill_result` depends on. A responder's reply is grounded
  via an optional `context_fn`, called fresh before every reply and
  injected as real local context — not yet wired to real data (the
  in-flight registry that would supply it doesn't exist until the
  cancellation work below is built), so no worker constructs one with a
  `context_fn` yet; wiring a placeholder now would mean grounding replies
  in something fabricated, defeating the point. Wired into both
  `__main__.py` entrypoints — a worker gets one whenever `LLM_BASE_URL` is
  set (this is the first thing in the whole codebase that gives a worker
  real LLM access, not just the head), and the head can now also be a
  *responder*, not only an initiator, symmetric with workers. 6 unit
  tests (`tests/test_dialogue.py`) drive a real two-sided conversation —
  round trip, multi-turn history, and context grounding — through two
  linked fake buses (no Redis needed: `AgentDialogue` is only ever fed via
  `.handle()`, never calls `Receive()` itself, so this is a faithful,
  fully in-process test of the real class, same rigor as `router.py`'s
  tests).
- ✅ **Cancellation (`cancellation.py`)** — `CancellationToken` gives a
  skill two fully opt-in ways to notice it's no longer needed: `ctx.cancelled`
  (a plain `Event`, for code that already loops/polls — `median.py`/`sum.py`'s
  ready-signal wait loops now check it) and `ctx.on_cancel(fn)` (fires `fn`
  immediately, on a new thread, for a skill doing one monolithic blocking
  call with no natural checkpoint — not exercised by any skill yet, since
  none currently need it, but the hook exists for one that does). A
  worker-local `CancellationRegistry` (one per worker process,
  `request_id -> CancellationToken`) is created by `worker.start_dispatch()`
  and populated *synchronously*, before a dispatch message's handler thread
  is even spawned — this matters because a `MessageRouter`'s
  `default_handler` calls are never concurrent with each other (exactly one
  polling thread, one at a time — see `router.py`), so a `skill_cancel` for
  the same `request_id` arriving right after can never race ahead of the
  token's creation. `head.run_skill()`'s retry now broadcasts `skill_cancel`
  to the superseded attempt's workers before starting the next one —
  without it, whichever worker was still coordinating that attempt would
  keep running uselessly until its own `coordinate_timeout` expired on its
  own, even though the head had already moved on. Tested at three levels:
  10 unit tests for the token/registry themselves (`tests/test_cancellation.py`,
  including the "registered after cancel() already fired" race); a real
  end-to-end test proving a genuinely stuck `MedianSkill.coordinate()` call
  returns in well under a second of a cancel arriving instead of running
  its full timeout (`tests/test_worker_cancellation.py`); and a test proving
  `run_skill()`'s retry actually sends exactly one `skill_cancel`, for the
  right (superseded) `request_id`, never the one that succeeds
  (`tests/test_run_skill_retry.py`).
- ✅ **Observability (`observability.py`)** — live cross-agent visibility,
  layered on top of `CancellationRegistry` rather than a second, parallel
  tracker: it already knows exactly the data ("what request_ids is this
  worker currently handling") this needs, so `CancellationRegistry` gained
  an *optional* `activity_mapper`/`agent_id` — when given, `create()`/
  `forget()` also publish this worker's current in-flight `request_id`s to
  a shared Mapper, keyed by agent, `AllGather()`-able by anyone as
  `observability.snapshot()`. Unlike scarlets' own agent registry
  (confirmed by reading `Messenger.Register()`/`ReportStatus()` to have no
  TTL at all — the same finding that made `gather_workers()`'s staleness
  filter necessary earlier), Mapper values *do* expire on their own
  (`scarletDataExpiry`, ~1hr default), so a crashed worker's activity
  entry doesn't linger forever the way the raw agent registry's would.
  Purely observational — nothing about dispatch, retry, or cancellation
  depends on it. A worker's `AgentDialogue` (`dialogue.py`) now gets a
  *real* `context_fn`, grounded in the registry's own live
  `in_flight_requests`, closing the exact gap flagged when `AgentDialogue`
  was first built ("no worker constructs one with a context_fn yet").
- ✅ **`RedisLogger` audit trail** — this ecosystem already has a working,
  idiomatic way to write timestamped, app/node-tagged status entries to
  Redis (`scarlets.utils.RedisLogger`, already used internally by
  `Messenger` for transport-level events) — extended into this codebase's
  own application-level lifecycle, not reinvented. Head side
  (`head.run_skill()`): every dispatch, every retry (and why), every
  `skill_cancel` broadcast, every final success/failure. Worker side
  (`worker.py`): every dispatch started, every `skill_cancel` received,
  every coordination finished (with its outcome). Together with the
  Mapper snapshot above, this is deliberately two different shapes for
  two different questions — Mapper is "what's happening *right now*" (one
  live value per agent, overwritten each time), `RedisLogger` is "what
  *happened*, and when" (an append-only entry per event) — see
  `observability.py`'s docstring for why one wouldn't substitute for the
  other. 3 real-Redis tests (`tests/test_observability.py`, since `Mapper`
  is Redis-backed and can't be faked in-process) prove two separate
  registries (standing in for two worker processes) publishing to the
  same shared Mapper produce a real cross-agent snapshot, not just
  read-your-own-writes.
- ✅ **Deliberation** — the last piece of the plan: a timeout no longer
  means an automatic mechanical retry. `run_skill()` gained optional
  `dialogue`/`llm_client` parameters; when both are given, a timeout
  triggers a real check-in conversation with the coordinator
  (`AgentDialogue`) — "how's this going?" — grounded in the coordinator's
  own real state (the observability work above is what makes that
  grounding real, not fabricated). A small, narrow LLM call (`_deliberate`
  — deliberately *not* `converse()`'s tool-calling loop; this is weighing
  one piece of qualitative evidence, not choosing a skill) reads the
  reply and decides `WAIT` (re-arm the original wait, no retry yet) or
  `RETRY` (proceed with the existing cancel-and-retry path). Bounded on
  two independent axes so this can never hang or loop forever:
  `max_check_ins` caps how many check-in rounds one attempt gets, and
  `check_in_timeout` bounds the check-in conversation itself, separately
  from the coordinator's own `coordinate_timeout`. Defaults to exactly the
  old mechanical behavior whenever `dialogue`/`llm_client` aren't supplied
  — every existing caller (all of `median`/`sum`/`combine`'s own tests,
  `test_run_skill_retry.py`) is unaffected. `converse()` now takes the
  same optional `dialogue` and threads it (plus its own `llm_client`, the
  same backend, no second client needed) into every `run_skill()` call it
  makes — wired end-to-end in `__main__.py`'s LLM-backed chat mode, not
  just available as an unused parameter.
  `tests/test_deliberation.py` proves all three real outcomes against a
  fake coordinator (a real `AgentDialogue` + scripted LLM, same rigor as
  `test_run_skill_retry.py`'s fake-worker pattern): a `WAIT` decision
  genuinely re-arms the wait and lets a late-arriving real result still
  succeed (not just get discarded); a `RETRY` decision proceeds through
  the existing cancel-and-retry path exactly as before; and the coordinator
  never answering the check-in *itself* correctly falls back to retry via
  `check_in_timeout`, without ever reaching the deliberation LLM call at
  all. One real bug caught while building this test file, worth noting: a
  missing `default_handler` wiring on the test's own head-side router
  silently dropped every check-in reply, making every scenario fall
  through to the `check_in_timeout` path regardless of what was scripted -
  a reminder that `AgentDialogue` replies need the same explicit routing
  `__main__.py` already does, not something automatic.
- ✅ **Validated against a real LLM backend** — every prior "not yet
  verified against a live endpoint" caveat in this file is now closed.
  Tested against Claude Sonnet 4.6 via Anthropic's OpenAI-SDK-compatibility
  endpoint (`LLMClient` needed zero code changes — it already spoke the
  right wire format). Six real-LLM tests, each opt-in (skipped unless
  `LLM_BASE_URL` is set, so the regular 82-test suite stays fast and
  credential-free), each writing a full transcript to `transcripts/`
  (`tests/transcript.py` — reconstructed directly from Redis, not
  instrumented/monkeypatched, since real subprocess workers mean a
  monkeypatch in the test process would never see their in-process
  `Send()` calls; Redis is the one place every message from every process
  actually lands):
  - `test_real_llm_median.py` — `converse()` correctly picks `median`
    across 3 real worker subprocesses, real answer narrated back.
  - `test_real_llm_variance.py` — the real test of "skills as alphabets,
    agents build paragraphs": with zero hints beyond "you have sum and
    combine tools available," the model reconstructed the variance
    formula itself, called `sum(identity)` and `sum(square)` **in the
    same turn** ("let me fire both at the same time") — a live
    confirmation that `converse()`'s concurrent-tool-call dispatch (from
    the async rewrite) is genuinely exercised, not just theoretically
    supported — then fed both real results into `combine` with the exact
    correct expression, matching `statistics.pvariance` to machine
    precision.
  - `test_real_llm_deliberation.py` — `_deliberate()` correctly decided
    WAIT/RETRY for three realistic coordinator status replies.
  - `test_real_llm_dialogue.py` — `AgentDialogue`'s real reply generation,
    the first worker-side LLM call in this codebase ever exercised
    against a real backend. **Found and fixed a real prompt-framing bug**:
    without an explicit identity system prompt, the model answered a
    check-in like a third party asked to interpret a report handed to it
    ("I don't actually have visibility into this distributed system...")
    instead of speaking as the coordinator reporting its own real state.
    `dialogue.py`'s `_system_prompt()` now establishes "you are agent X,
    this is your own real, current state, answer directly" before every
    responder call — re-running the same test afterward produced a
    confident, in-character reply instead ("Still waiting on one
    contributor... Monitoring, but not alarmed yet.").
  - Median/variance tests use a unique `APP_ID` per test, since
    `transcript.py` scans an entire bus namespace by name — sharing one
    with another test would mix their messages together.
- ✅ **Real end-to-end deliberation, and two follow-up fixes it motivated
  directly.** `tests/test_real_llm_stuck_and_checkin.py` forces a real,
  non-artificial-agent-behavior stuck scenario — real subprocess workers,
  real coordinator with its own real LLM access, real check-in, real
  deliberation — by mutating only the *head's own in-process copy* of the
  skill's `coordinate_timeout` (a different Python object than whatever
  the worker subprocess's own `discover_skills()` constructed), so the
  head gets impatient while the coordinator is still genuinely, honestly
  working. Building this surfaced two real gaps, both now fixed:
  - **`timeout_scan_interval` is now properly configurable.**
    `TimeoutWatcher` only scans for expired deadlines every 0.5s by
    default — a real floor on how fast *any* timeout anywhere fires,
    discovered when this test's first two attempts (even down to a 1ms
    nominal deadline) both completed before the watcher ever checked.
    `MessageRouter`/`Buses` now accept `timeout_scan_interval`, threaded
    from a new `HarnessConfig.timeout_scan_interval` field
    (`TIMEOUT_SCAN_INTERVAL` env var, defaults to the same 0.5s as
    before) — no more reaching into a router's private `_watcher`
    attribute to change it.
  - **Retry/check-in bounds are now configurable via `HarnessConfig`
    too** (`MAX_ATTEMPTS`, `REPLY_SLACK`, `MAX_CHECK_INS`,
    `CHECK_IN_TIMEOUT` env vars) — `run_skill()`'s corresponding
    parameters now default to `None`, meaning "use config's value"
    (matching the old hardcoded defaults exactly, so every existing
    caller is unaffected), rather than only being reachable by passing an
    explicit override at every call site.
  - **The production `context_fn`'s data is now genuinely specific, not
    just present.** `CancellationToken` gained `skill_name`/`started_at`
    plus an opt-in `update_progress()` a skill's `coordinate()` calls as
    it goes (`ctx.report_progress(ready_count=..., expected_count=...)` —
    wired into `median.py`/`sum.py`). `CancellationRegistry.snapshot()`
    now returns this per-request (skill, elapsed time, ready/expected
    counts), and a new `describe_in_flight()` formats it into explicit
    sentences ("Request X: coordinating 'median', started 4.2s ago, 2 of
    3 contributors have checked in") rather than a bare ID list or raw
    JSON dump — directly closes the gap the first version of this test
    exposed (a coordinator with only a bare ID list to go on had nothing
    to reason from, so a real model hedged and even recommended RETRY on
    a computation that was simply early, not stuck). Re-running the same
    test after this fix: the coordinator answered specifically ("started
    just 0.0 seconds ago, no contributor progress reported yet"), the
    deliberation call correctly decided WAIT instead of RETRY, and the
    computation went on to succeed normally — the whole point of
    deliberation existing in the first place.
- ✅ **The check-in itself is now free-flowing, not a fixed script on
  either side.** Previously only the coordinator's *reply* was real LLM
  generation — the head's opening question was one hardcoded f-string, and
  the exchange was always exactly one round: ask, get an answer, decide.
  Now:
  - `_compose_checkin_question()` has the head's own LLM write the
    opening question itself, grounded in the skill name, the timeout, and
    which check-in round this is — not the same fixed sentence every time.
  - `_deliberate_or_followup()` replaces the old single-shot `_deliberate()`
    call *within* a check-in: given the whole conversation so far, it can
    answer WAIT, RETRY, or `ASK: <a genuine follow-up question>` — and if
    it asks, `dialogue.reply()` continues the same conversation (the
    coordinator answers with its own session history intact, via
    `AgentDialogue`'s existing multi-turn support) before deliberating
    again. Bounded by a new `check_in_max_turns` (`HarnessConfig` field,
    `CHECK_IN_MAX_TURNS` env var, default 3) so this can't loop forever —
    once exhausted, a decision is forced.
  - `tests/test_deliberation.py::test_followup_question_continues_the_checkin_conversation_before_deciding`
    scripts an ASK → reply → WAIT exchange deterministically, proving the
    mechanism itself (re-entering `on_checkin_reply` via `dialogue.reply()`,
    both sides seeing the growing real transcript) rather than relying on
    a live model to happen to choose that path on any given run.
  - Re-run against a real backend after this change
    (`tests/test_real_llm_stuck_and_checkin.py`): two separate attempts
    produced two genuinely different opening questions (e.g. "Hey, just
    checking in on that median computation... it's been a bit longer than
    expected. Do you have an update on where things stand?" vs. a
    differently-worded question on the retry) — real variation, not a
    template fill. The coordinator's grounded answer ("I don't have
    anything in flight right now... that job isn't something I'm
    currently tracking") correctly drove a RETRY decision both times; this
    particular run didn't need a follow-up (the answer was already
    unambiguous), which is exactly why the deterministic scripted test
    above exists to cover that branch on its own. See
    `transcripts/test_real_stuck_coordinator_triggers_a_real_checkin_and_deliberation.md`
    for the full exchange.
- ✅ **Packaged into a Docker image** (`Dockerfile`, extends
  `ghcr.io/disys-lab/scarlet-agent-base:0.5.0`, matches
  scarlet-composer-studio's own hello_agent quickstart convention) — built
  and run for real against a disposable Redis (not just a syntax check):
  `docker build` succeeds, and the running container reaches `worker
  online, skills=['combine', 'median', 'sum'], dialogue=off`, a real
  Redis-backed capability registration. `docker-compose.yml`/`.env.example`
  run it alongside a `scarlet-composer` sibling container for local dev,
  mirroring the quickstart example (`scarlet-composer` is a standalone
  operator UI, never combined into an agent's own image anywhere in this
  ecosystem). `ROLE=head` isn't yet suited to run this way - `__main__.py`'s
  head branch is currently an interactive REPL reading `sys.stdin`, not a
  headless daemon; documented in the Dockerfile rather than silently
  shipped broken.
- ✅ **`NODE_ADDRESS` is now genuinely optional, matching Gustavo's actual
  deployment contract.** Checked against scarlet-composer-studio's real
  docs and source (`docs/concepts/identity.md`,
  `scarlets/types/ScarletBase.py`) while verifying Gustavo compatibility:
  Gustavo's documented app-config pattern deliberately leaves
  `NODE_ADDRESS: ""` empty and expects the agent to resolve it itself -
  this harness previously assumed the opposite (`from_env()` raised if
  `NODE_ADDRESS` was unset) and would have crashed on every node under a
  real Gustavo deployment. `_resolve_node_address()` now mirrors
  `ScarletBase._resolveNodeAddress()`'s real priority chain exactly (env
  var → the Gustavo manager's `/api/v2/getNodeInfo` endpoint via
  `MANAGER_HOST`/`MANAGER_PORT` → local hostname IP → `"127.0.0.1"`),
  including its `app_id` query-param shape (not `node`, as the docs'
  simplified description states - the real implementation was the source
  of truth here) and its `os.environ` side-effect so other scarlets
  primitives constructed later in the same process skip a redundant call.
  `tests/test_config.py` covers all four branches with mocked
  `requests`/`socket`, no real network calls.
  - **Real bug found via an actual container run, not just unit tests**:
    `scarlet-agent-base`'s own Dockerfile (and this harness's own,
    extending it) declare several optional vars as `ENV KEY=""`
    placeholders rather than leaving them genuinely unset -
    `os.environ.get(key, default)` can't tell that apart from a real
    override, since the key is present either way. `device_group` came
    back `""` (not the intended `f"{app_id}_subagent"`) from a real
    `docker run` before this was fixed. `_env()` now treats an
    explicitly-empty value as absent everywhere in `config.py` -
    `tests/test_config.py::test_empty_string_env_vars_treated_as_unset`
    reproduces the exact real-container shape (present-but-empty, not
    merely absent) so this class of bug can't silently return.
- ✅ **MCP gateway** (`mcp_server.py`) — wraps `head.converse()` as a single
  MCP tool (`ask_scarlet_agent(message: str) -> str`), replacing
  `__main__.py`'s stdin REPL as the human/external-agent entry point. A
  different, higher layer than scarlets' own documented MCP integration
  (`Messenger.AsTools()` in scarlet-composer-studio's docs/guides/
  llm-integration.md, which exposes raw bus primitives like `send_message`/
  `gather_status` as MCP tools, requiring the external client's own LLM to
  do its own skill-selection reasoning) - this exposes the already-built
  `converse()` loop instead, so a caller doesn't need to know median/sum/
  combine exist at all. Skill selection, dispatch, retry, and deliberation
  all still happen inside this harness using its own LLM backend; only the
  entry point changes. Requires `ROLE=head` and `LLM_BASE_URL` (no manual-
  dispatch fallback, unlike the stdin REPL). `MCP_TRANSPORT` env var
  selects `stdio` (default - a client launches this process directly,
  e.g. Claude Desktop's local MCP config) or `streamable-http`/`sse` (a
  real deployment behind Gustavo would expose `MCP_HOST`/`MCP_PORT`) - the
  `streamable-http` mode is also a genuine headless alternative for a head
  role, needing no `sys.stdin` at all (see the Dockerfile's own note on
  this).
  - **Verified against the real MCP protocol, not just an in-process
    call**: `tests/test_real_llm_mcp_server.py` uses the real `mcp` client
    SDK (`mcp.client.stdio.stdio_client`) to spawn `mcp_server.py` as an
    actual subprocess and speak the real MCP wire protocol to it
    (`initialize` → `list_tools` → `call_tool`) - not a shortcut that
    calls the tool function directly. That subprocess's own `converse()`
    call drove a real distributed median computation across 3 real
    worker subprocesses and real Redis, and a real Claude Sonnet 4.6
    reply ("The global median across all worker agents is 5.0...") came
    back through the MCP tool-call boundary correctly. See
    `transcripts/test_ask_scarlet_agent_drives_a_real_median_computation_over_real_mcp.md`.

## Design decisions worth knowing

- **Env var vocabulary matches `scarlet_composer_agentic_design/DESIGN_v3.md`
  §15 exactly** (`REDIS_HOST`/`PORT`/`AUTH_TOKEN`, `APP_ID`, `NODE_ADDRESS`,
  `DEVICE_GROUP`, `HEAD_BUS`) — this harness is meant to be a drop-in
  Gustavo app, not a parallel identity system. `ROLE` and `LLM_*` are new;
  they don't exist in scarlet-composer-studio itself.
- **Capability reporting shape matches DESIGN_v3.md §8.3** exactly
  (`status`/`role`/`capabilities`/`data_sources`/`mcp_tools`/`device_group`/
  `node_address`) so agents built with this harness show up correctly in
  scarlet-composer-studio's own Agents dashboard, not just to each other.
- **`Skill.coordinator_for()` defaults to a random worker, never the head.**
  Nothing about `Mapper`/`Federator` requires the head to call
  `AllGather()`/`Aggregate()` itself — that's an application-level choice,
  and defaulting to the head would make it a bottleneck for every skill's
  aggregation step under concurrent invocations, not just dispatch. The head
  retains control over task *routing* (DESIGN_v3.md §8.5); that's a
  different thing from being where computation happens. A skill can still
  override `coordinator_for()` to return `ctx.agent_id` when the aggregation
  is cheap enough that the extra two message hops aren't worth it — an
  explicit opt-in, not the default.
- **A worker never runs its own LLM call for a well-defined skill.** Once
  the head has decided which skill applies, the message it sends is already
  fully structured — re-interpreting it with another LLM call on the worker
  side would just reintroduce ambiguity one hop later. Worker-side dispatch
  is a plain deterministic lookup (`worker.handle_message`).
- **One Docker image, role picked by `ROLE` env var** is the intended
  packaging (not built yet) — same spirit as scarlet-composer-studio's own
  `APP_ID`/`DEVICE_GROUP` pattern. Keeps the skill library identical on
  head and worker by construction; no version-skew risk between two images.
- **`LOCAL_NUMBERS` env var** (comma-separated floats) is a deliberate
  placeholder for scarlet-composer-studio's own three-tier data source
  system (DESIGN_v3.md §9), not a permanent design choice.
- **`MessageRouter` (`router.py`) is now the sole caller of `Receive()`** on
  every bus, via `Buses.global_router`/`local_router` — nothing else may
  call `global_bus.Receive()`/`local_bus.Receive()` directly. This isn't
  stylistic: scarlets' `Messenger` transport has no way to filter or peek
  without consuming, so any second independent caller of `Receive()` on the
  same bus races the first and can permanently lose a message meant for it.
  The router demultiplexes by `request_id`; skills call
  `ctx.buses.local_router.receive_for(request_id, timeout)` instead of
  `ctx.buses.local_bus.Receive(timeout)`, and must call `.forget(request_id)`
  once done (success or error) since queues are keyed by UUID and never
  auto-expire.

## Running the tests

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e . -r requirements.txt
python3 -m pytest tests/ -v
```

`tests/test_median_skill.py` spins up a disposable local Redis via `docker
run` (removed at the end of the session, never a real deployment target),
spawns 3 real worker subprocesses, and drives a full median computation
through the actual dispatch code — no mocks on the scarlets side.
