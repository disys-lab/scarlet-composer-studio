# Architecture

What each part of `scarlet_agentic_harness` does, and how a question
becomes a distributed computation.

## The path a question takes

```
human question
   │
   ▼
mcp_server.ask_scarlet_agent          MCP tool, one per head process
   │
   ▼
head.converse → Conversation          the turn loop: ask the model, run
   │                                  what it calls, repeat
   ▼
dispatch.run_skill → SkillDispatch    pick workers, send, await, retry
   │
   ├── CompoundSkill? ──► PlanRunner   run a plan of other skills
   │
   ▼
worker.handle_message                 on each worker
   │
   ▼
skill.contribute(ctx, request)        local compute, publish via Mapper
   │
   ▼
skill.coordinate(ctx, request, …)     on exactly one worker: aggregate
```

The head decides *routing*. It does not compute: `coordinator_for()`
defaults to a random worker, so aggregation never piles onto one process.

## Modules by role

### Entry points

| Module | Role |
|---|---|
| `__main__.py` | Process entrypoint. Boots a head or a worker from env config. |
| `mcp_server.py` | Wraps `converse()` as a single MCP tool. This is what notebooks call. |
| `worker.py` | Worker-side message handling. |
| `worker_dispatcher.py` | Routes one inbound bus message to the right handler. |

### The head's conversation

| Module | Role |
|---|---|
| `head.py` | `converse()` - the public entry to one exchange. |
| `conversation.py` | `Conversation`, the turn loop itself, plus the per-call callbacks. |
| `conversation_store.py` | Thread-safe transcript, keyed by conversation id. |
| `converse_result.py`, `conversation_did_not_conclude.py` | The two outcomes. |
| `joiner.py` | Waits for every tool call in one turn to answer. |
| `reasoning.py`, `publishing_event_handler.py` | Publish the head's reasoning to the bus so something other than this process can watch it. |

### Dispatch

| Module | Role |
|---|---|
| `dispatch.py` | `run_skill` / `run_plan` - the public surface. |
| `skill_dispatch.py` | `SkillDispatch` (shared), `SkillAttempt` (one try), `CheckIn` (one check-in round). |
| `plan_runner.py` | `PlanRunner` / `StepResult` - executes a compound skill's plan. |
| `router.py`, `timeout_watcher.py`, `timeout_handler.py` | Per-key reply routing with deadlines. |
| `cancellation*.py` | Cooperative cancellation, so a superseded attempt stops work. |

A retry is a **new attempt with a new request_id**, not a re-send. That is
why per-attempt state is per-object: cancelling a superseded attempt has
to reach exactly that attempt's workers.

### Data access

| Module | Role |
|---|---|
| `local_config.py` | Reads `~/.scarlet/config.yaml` - the only way a worker learns about its data. |
| `data_profile.py` | Profiles each source at boot: rows, numeric columns, temporal columns and their format. |
| `local_matrix.py` | Turns an objective into a 2-D numeric matrix: choose a source, build SQL, convert. |
| `skills/predicate.py` | Builds `WHERE` clauses from structured conditions. Also renders Flux and PI. |

Nothing here is ever told a file path by the head. A worker is given an
objective and resolves its own source, its own columns and its own query.

### Agent-to-agent

| Module | Role |
|---|---|
| `dialogue.py` | `AgentDialogue` - multi-turn natural-language conversation between any two agents. |
| `scarlet_minting.py` | A worker mints a new scarlet mid-task via its own LLM reasoning. |
| `observability.py` | Live in-flight activity, published to a shared Mapper. |

### Supporting

`buses.py` (two-channel Messenger setup), `config.py` (env config),
`context.py` (`HarnessContext`, what a skill is handed), `chat_client.py`
(the LLM protocol), `result_box.py`, `noop_cancellation.py`.

## The skill catalogue

Eleven skills ship. `skills/registry.py` discovers them by walking the
package - adding a module is all it takes, and dispatch never changes.

### Core skills

| Skill | Shape |
|---|---|
| `sum_core` | Associative reduction over a `Federator`. `transform=identity\|square` gives Σx and Σx², which with `n` is enough for mean and variance. |
| `median` | Not associative - needs the partitioned data and a real merge. Backed by `Mapper.AllGather()`. |
| `combine` | Local arithmetic over an AST-whitelisted expression. Closes the composition loop without a skill per formula. |
| `agree_representation` | Workers propose their columns; the intersection is the shape everyone contributes. |
| `query_feature` | Read a named source, or state an objective and let each worker pick its own. |
| `list_sources`, `list_tags` | What a worker holds, and which columns exist. |
| `create_scarlet` | A worker mints a scarlet mid-task. |

### Compound skills

A `CompoundSkill` is a plan over other skills, run by `PlanRunner` over a
shared namespace. The ordering lives in the skill, not in the prompt.

| Skill | Plan |
|---|---|
| `sum` | `agree_representation` → `sum_core` |
| `mean` | `agree_representation` → `sum_core` → `combine` |
| `variance` | `agree_representation` → `mean` → `sum_core` → `combine` |

`variance` nests `mean`, and consensus runs **once** for the whole nested
plan: `columns` is already bound in the namespace when `mean` is reached,
so its own `agree_representation` step is skipped.

Three rules govern stepping, each a separate branch so removing one is
visible:

1. a step with no outputs always runs - it is a check
2. a step whose outputs are all bound is skipped
3. a failed step aborts the plan, carrying the child's `retryable` upward

Nesting is capped by `MAX_PLAN_DEPTH`.

## Row filtering

Any aggregating skill takes `conditions` - a list of
`{"column", "op", "value"}`. The LLM never writes SQL: the operator comes
from a whitelist, the column is checked against the worker's profile, and
the value is parsed before formatting.

```python
conditions=[
    {"column": "timestamp", "op": "gte", "value": "2026-01-01T00:00:00"},
    {"column": "timestamp", "op": "lt",  "value": "2026-01-01T00:30:00"},
]
```

Three properties are load-bearing, and each fails silently if broken:

- **The predicate is settled once and applied identically.** If one worker
  filters and another does not, the fleet averages two different questions
  and returns a believable number. No shape check can catch it - the
  columns, widths and dtypes all match.
- **Filter columns and aggregate columns are different sets.** Only
  numeric columns can be aggregated; a time window filters on a timestamp,
  which never is.
- **A worker matching no rows is reported, not silently zero.** An empty
  result reads as "nothing here", and the result names which workers were
  empty.

Date formats may differ per worker. The fleet agrees one logical instant,
and each worker casts its own column to it. A column whose format is
ambiguous - `03/01/2025` parses as both `%m/%d/%Y` and `%d/%m/%Y` - is left
untyped and refused, because guessing shifts a whole series by months
without erroring.

## Extending it

- **A new skill**: drop a module under `skills/core/`. See
  [AGENTS.md](../AGENTS.md) for the full contract, including tests, test
  data and a notebook.
- **A new compound skill**: a `plan` of `Step`s and a `returns` mapping.
  No dispatch changes.
- **A new connector dialect**: `predicate.py` renders structured
  conditions; add a renderer beside `render_flux` / `render_pi`.
