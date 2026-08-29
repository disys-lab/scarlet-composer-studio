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

Two skills exist so far, deliberately chosen to exercise different shapes:

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

Together these prove the `Skill` interface generalizes past "head
aggregates centrally" *and* past "every skill needs `Mapper`" — a new skill
is a new module under `skills/`, never a change to `head.py`/`worker.py`'s
dispatch logic.

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
- No composition layer yet — nothing calls `sum` twice and combines the
  results automatically; that's still a manual arithmetic step in the test,
  proving the *data* is composable, not yet that the *system* composes it.
  The natural next piece is the local, non-distributed "combine" tool
  discussed for variance, plus `converse()` actually making two tool calls
  in sequence for a real composed request.
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
