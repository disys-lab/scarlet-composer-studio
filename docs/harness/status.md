# Status / build history

Detailed, chronological record of what's been built and verified in the
harness, kept as a real historical record rather than condensed away.

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
  client object (`tests/test_llm_client.py`) — **and also verified against
  a real live backend** (Claude Sonnet 4.6, via Anthropic's
  OpenAI-SDK-compatibility endpoint) with zero code changes needed.
  `__main__.py`'s head role uses `LLMClient` + `converse()` for real
  whenever `LLM_BASE_URL` is set.
- ✅ **`sum` skill** — `Federator`-backed, parameterized (`transform`),
  reports total element count `n` correctly (co-aggregated with the sum, not
  `len(workers)`). End-to-end tested for both transforms plus a real
  variance derived from two `sum` calls (`tests/test_sum_skill.py`).
- ✅ **`combine` skill** — generic expression+variables evaluator
  (`safe_eval`, AST-whitelisted), runs on a randomly-chosen worker, no
  readiness handshake needed. `tests/test_variance_composition_end_to_end.py`
  chains two real `sum` calls into a real `combine` call and checks the
  result against `statistics.pvariance` — the system composes sum→combine
  automatically via `run_skill`, not just by hand in a test.
- ✅ **Auditability** — `converse()` returns a `ConverseResult` (`answer` +
  the full canonical-shape `messages` transcript), not a bare string, and
  takes an optional `on_event` callback fired synchronously for narration,
  tool calls, tool results, and the final answer as they happen.
  `ConversationDidNotConclude` also carries the partial transcript for
  post-mortem. `__main__.py`'s LLM-backed chat mode logs every event to
  stderr as JSON as a real (if minimal) live audit trail.
- ✅ **Worker-level concurrency** — a worker no longer blocks its whole
  dispatch loop inside one `skill.coordinate()` call while it runs. Fixed
  via `router.py`'s `MessageRouter`: exactly one background thread owns a
  bus's `Receive()` (scarlets' `Messenger` is a strict per-agent FIFO with
  unconditional ack-on-read and no peek/filter — confirmed by reading the
  installed package's source — so two independent callers of `Receive()`
  on the same bus can and will silently steal messages meant for each
  other). The router demultiplexes by `request_id` into per-request
  queues; unmatched (unsolicited) messages go to a `default_handler`, which
  is how `worker.start_dispatch()` spawns a thread per incoming
  `skill_contribute`/`skill_coordinate` instead of looping.
  `tests/test_worker_concurrency.py` forces two different skill invocations
  onto the *same* coordinator concurrently and asserts both return fully
  correct results.
- ✅ **Retry on transient mid-computation failure** — `run_skill()` retries
  (fresh `request_id`, fresh worker survey, possibly a new coordinator)
  when a result is marked `"retryable": True` — set by median/sum for
  failures that are plausibly transient. `combine`'s logical errors (bad
  expression) are explicitly `"retryable": False`. A skill that doesn't set
  the flag defaults to *not* retryable. Also required teaching
  `Buses.gather_workers()` a staleness filter (`max_staleness`, default
  60s): scarlets' own registry entries never expire on their own (a plain
  `r.set()`, no TTL; only the 30s heartbeat keeps a live agent's timestamp
  moving). `tests/test_run_skill_retry.py` drives this deterministically.
  Known, accepted gap: excluding a genuinely-dead worker from a retry
  relies entirely on the staleness filter — a worker that dies and is
  replaced by a fresh one reporting under the same `agent_id` within the
  staleness window would not be distinguished from the original. Would need
  an upstream change to scarlets' own registry semantics (instance IDs are
  already tracked internally — see `Messenger._instanceId` — just not
  surfaced through `GatherStatus()` today).
- ✅ **`run_skill()`/`converse()` are fully async — dispatch-and-return,
  never block-and-wait.** Both functions' calling convention changed from
  returning a value to firing a callback (`on_result`/`on_done`) on some
  later thread, once. Built on `router.py`'s `on_key()` non-blocking
  registration, `timeout_watcher.py`'s single shared deadline-scanning
  thread, and `conversation_store.py`'s thread-safe state. `converse()`'s
  tool calls within one turn dispatch *concurrently* and rejoin in the
  model's original call order regardless of completion order (`_Joiner`).
  `tests/helpers.py`'s `run_skill_sync()`/`converse_sync()` give tests (and
  `__main__.py`'s interactive CLI) a way to block on one specific call's
  result via a `threading.Event`. All tests that called the old synchronous
  `run_skill()`/`converse()` directly were rewritten against the new
  callback contract.
- ✅ **`AgentDialogue` (`dialogue.py`)** — generalized agent-to-agent
  natural-language conversation, riding the same buses as everything else.
  One generic message envelope (`agent_message`: `conversation_id` +
  free-form `content`), not a new fixed-schema type per use case. Not built
  on `router.py`'s `on_key()`: an incoming `agent_message` can be either a
  reply to a conversation this agent started or a brand-new one someone
  else started, and only the message reveals which — `AgentDialogue` keeps
  its own small `conversation_id -> handler` registry, fed by a bus's
  `default_handler`. A responder's reply is grounded via an optional
  `context_fn`, called fresh before every reply and injected as real local
  context. Wired into both `__main__.py` entrypoints — a worker gets one
  whenever `LLM_BASE_URL` is set, and the head can also be a *responder*,
  not only an initiator. 6 unit tests (`tests/test_dialogue.py`) drive a
  real two-sided conversation through two linked fake buses.
- ✅ **Cancellation (`cancellation.py`)** — `CancellationToken` gives a
  skill two fully opt-in ways to notice it's no longer needed: `ctx.cancelled`
  (a plain `Event`) and `ctx.on_cancel(fn)`. A worker-local
  `CancellationRegistry` (one per worker process, `request_id ->
  CancellationToken`) is created by `worker.start_dispatch()` and populated
  *synchronously*, before a dispatch message's handler thread is even
  spawned. `head.run_skill()`'s retry broadcasts `skill_cancel` to the
  superseded attempt's workers before starting the next one. Tested at
  three levels: unit tests for the token/registry themselves
  (`tests/test_cancellation.py`); a real end-to-end test proving a
  genuinely stuck `MedianSkill.coordinate()` call returns in well under a
  second of a cancel arriving (`tests/test_worker_cancellation.py`); and a
  test proving `run_skill()`'s retry sends exactly one `skill_cancel`, for
  the right (superseded) `request_id` (`tests/test_run_skill_retry.py`).
- ✅ **Observability (`observability.py`)** — live cross-agent visibility,
  layered on top of `CancellationRegistry`: it gained an *optional*
  `activity_mapper`/`agent_id` — when given, `create()`/`forget()` also
  publish this worker's current in-flight `request_id`s to a shared Mapper,
  keyed by agent, `AllGather()`-able by anyone as `observability.snapshot()`.
  Unlike scarlets' own agent registry, Mapper values *do* expire on their
  own (`scarletDataExpiry`, ~1hr default). Purely observational. A worker's
  `AgentDialogue` now gets a *real* `context_fn`, grounded in the
  registry's own live `in_flight_requests`.
- ✅ **`RedisLogger` audit trail** — extends `scarlets.utils.RedisLogger`
  (already used internally by `Messenger` for transport-level events) into
  this codebase's own application-level lifecycle. Head side
  (`head.run_skill()`): every dispatch, every retry (and why), every
  `skill_cancel` broadcast, every final success/failure. Worker side
  (`worker.py`): every dispatch started, every `skill_cancel` received,
  every coordination finished. Deliberately two different shapes for two
  different questions: Mapper is "what's happening *right now*" (one live
  value per agent, overwritten each time), `RedisLogger` is "what
  *happened*, and when" (an append-only entry per event). 3 real-Redis
  tests (`tests/test_observability.py`) prove two separate registries
  publishing to the same shared Mapper produce a real cross-agent snapshot.
- ✅ **Deliberation** — a timeout no longer means an automatic mechanical
  retry. `run_skill()` gained optional `dialogue`/`llm_client` parameters;
  when both are given, a timeout triggers a real check-in conversation with
  the coordinator (`AgentDialogue`) — grounded in the coordinator's own
  real state. A small, narrow LLM call (`_deliberate`) reads the reply and
  decides `WAIT` (re-arm the original wait) or `RETRY` (proceed with the
  existing cancel-and-retry path). Bounded on two independent axes:
  `max_check_ins` and `check_in_timeout`. Defaults to exactly the old
  mechanical behavior whenever `dialogue`/`llm_client` aren't supplied.
  `tests/test_deliberation.py` proves all three real outcomes against a
  fake coordinator.
- ✅ **The check-in itself is free-flowing, not a fixed script on either
  side.** `_compose_checkin_question()` has the head's own LLM write the
  opening question itself, grounded in the skill name, the timeout, and
  which check-in round this is. `_deliberate_or_followup()` can answer
  WAIT, RETRY, or `ASK: <a genuine follow-up question>` — and if it asks,
  `dialogue.reply()` continues the same conversation before deliberating
  again. Bounded by `check_in_max_turns` (default 3).
  `tests/test_deliberation.py::test_followup_question_continues_the_checkin_conversation_before_deciding`
  scripts an ASK → reply → WAIT exchange deterministically. Re-run against
  a real backend: two separate attempts produced two genuinely different
  opening questions — real variation, not a template fill. See
  `transcripts/test_real_stuck_coordinator_triggers_a_real_checkin_and_deliberation.md`.
- ✅ **Real end-to-end deliberation**, and two follow-up fixes it motivated:
  `timeout_scan_interval` is now properly configurable (`TimeoutWatcher`
  only scans every 0.5s by default, a real floor on how fast any timeout
  fires); retry/check-in bounds are now configurable via `HarnessConfig`
  too (`MAX_ATTEMPTS`, `REPLY_SLACK`, `MAX_CHECK_INS`, `CHECK_IN_TIMEOUT`);
  and the production `context_fn`'s data is now genuinely specific
  (`CancellationToken` gained `skill_name`/`started_at` plus an opt-in
  `update_progress()`, and `describe_in_flight()` formats it into explicit
  sentences like "Request X: coordinating 'median', started 4.2s ago, 2 of
  3 contributors have checked in").
- ✅ **Validated against a real LLM backend** — Claude Sonnet 4.6 via
  Anthropic's OpenAI-SDK-compatibility endpoint. Six real-LLM tests, each
  opt-in (skipped unless `LLM_BASE_URL` is set), each writing a full
  transcript to `transcripts/` (reconstructed directly from Redis, since
  real subprocess workers mean a monkeypatch in the test process would
  never see their in-process `Send()` calls):
  - `test_real_llm_median.py` — `converse()` correctly picks `median`
    across 3 real worker subprocesses, real answer narrated back.
  - `test_real_llm_variance.py` — with zero hints beyond "you have sum and
    combine tools available," the model reconstructed the variance formula
    itself, called `sum(identity)` and `sum(square)` **in the same turn**,
    then fed both real results into `combine` with the exact correct
    expression, matching `statistics.pvariance` to machine precision.
  - `test_real_llm_deliberation.py` — `_deliberate()` correctly decided
    WAIT/RETRY for three realistic coordinator status replies.
  - `test_real_llm_dialogue.py` — `AgentDialogue`'s real reply generation.
    **Found and fixed a real prompt-framing bug**: without an explicit
    identity system prompt, the model answered a check-in like a third
    party asked to interpret a report handed to it, instead of speaking as
    the coordinator reporting its own real state. `dialogue.py`'s
    `_system_prompt()` now establishes "you are agent X, this is your own
    real, current state, answer directly" before every responder call.
- ✅ **Packaged into a Docker image** (`Dockerfile`, extends
  `ghcr.io/disys-lab/scarlet-agent-base`) — built and run for real against
  a disposable Redis: `docker build` succeeds, and the running container
  reaches `worker online, skills=['combine', 'median', 'sum'],
  dialogue=off`, a real Redis-backed capability registration.
  `ROLE=head` isn't yet suited to run this way — `__main__.py`'s head
  branch is currently an interactive REPL reading `sys.stdin`, not a
  headless daemon; documented in the Dockerfile rather than silently
  shipped broken. See [Deployment](deployment.md).
- ✅ **`NODE_ADDRESS` is genuinely optional, matching Gustavo's actual
  deployment contract.** Gustavo's documented app-config pattern
  deliberately leaves `NODE_ADDRESS: ""` empty and expects the agent to
  resolve it itself — this harness previously assumed the opposite and
  would have crashed on every node under a real Gustavo deployment.
  `_resolve_node_address()` mirrors `ScarletBase._resolveNodeAddress()`'s
  real priority chain exactly (env var → the Gustavo manager's
  `/api/v2/getNodeInfo` endpoint → local hostname IP → `"127.0.0.1"`).
  **Real bug found via an actual container run**: `ENV KEY=""` placeholders
  in the Dockerfile made `os.environ.get(key, default)` unable to tell an
  explicit empty override from a real one — `device_group` came back `""`
  instead of the intended default. `_env()` now treats an
  explicitly-empty value as absent everywhere in `config.py`.
- ✅ **MCP gateway** (`mcp_server.py`) — wraps `head.converse()` as a single
  MCP tool (`ask_scarlet_agent(message: str) -> str`), replacing
  `__main__.py`'s stdin REPL as the human/external-agent entry point. A
  different, higher layer than scarlets' own documented MCP integration
  (`Messenger.AsTools()`, which exposes raw bus primitives, requiring the
  external client's own LLM to do its own skill-selection reasoning) — this
  exposes the already-built `converse()` loop instead. Requires `ROLE=head`
  and `LLM_BASE_URL`. `MCP_TRANSPORT` selects `stdio` (default) or
  `streamable-http`/`sse` (a genuine headless alternative for a head role).
  **Verified against the real MCP protocol**: `tests/test_real_llm_mcp_server.py`
  uses the real `mcp` client SDK to spawn `mcp_server.py` as an actual
  subprocess and speak the real MCP wire protocol to it — that subprocess's
  own `converse()` call drove a real distributed median computation across
  3 real worker subprocesses and real Redis. See
  `transcripts/test_ask_scarlet_agent_drives_a_real_median_computation_over_real_mcp.md`.
- ✅ **Local-first data access**: `local_config.py` (site-owned
  `~/.scarlet/config.yaml`), the `query_feature` and `list_tags` skills,
  and `create_scarlet` (mint a new scarlet mid-task via real LLM reasoning)
  — see [Design Decisions](design.md) for the rationale.
