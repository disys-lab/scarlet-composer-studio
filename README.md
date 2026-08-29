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
  client object (`tests/test_llm_client.py`) — not yet verified against a
  *live* backend, since no credentials exist yet. `__main__.py`'s head role
  now uses `LLMClient` + `converse()` for real once `LLM_BASE_URL` is set;
  that specific wiring is the one piece in this codebase still unverified
  end-to-end, purely because there's nothing to point it at yet.
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
- Not packaged into a Docker image, no Gustavo app config written, nothing
  deployed to any device group.

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
