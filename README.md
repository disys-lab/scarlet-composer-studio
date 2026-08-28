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

The reference implementation is a distributed **median**: workers each hold
a private, unordered list of numbers; the head assigns one worker as
coordinator (workers never self-assign — see
`scarlet_composer_agentic_design/DESIGN_v3.md` §8.5); the coordinator
gathers every worker's sorted local partition via `Mapper.AllGather()` and
merges them into the true global median. Median specifically can't be built
on `Federator` (it isn't an associative reduction the way sum/mean are), so
it's a genuine test of whether the `Skill` interface generalizes past the
"head aggregates centrally" case — a new skill is a new module under
`skills/`, never a change to `head.py`/`worker.py`'s dispatch logic.

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
- ⏳ The head's LLM tool-loop (turning a human's free-text request into a
  skill invocation) is **not implemented** — it needs a real
  OpenAI-compatible backend (litellm credentials, per the plan) before it's
  buildable/testable. `head.run_skill()` — the actual dispatch mechanics —
  works today with no LLM at all; `__main__.py`'s head role currently falls
  back to a manual JSON-lines-on-stdin dispatch mode for exactly this reason.
- Not packaged into a Docker image, no Gustavo app config written, nothing
  deployed to any device group. That's the deliberate next phase once the
  interface has more than one skill validating it (sum/mean are the natural
  next test, since they're `Federator`-shaped rather than `Mapper`-shaped).

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
