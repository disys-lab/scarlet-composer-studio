# Core Concepts

## Head and workers

One process runs as `ROLE=head`, any number run as `ROLE=worker` — same
Docker image either way, the role is picked at startup. The head accepts a
task (from a human, or from `converse()`'s LLM tool-calling loop) and
dispatches it to workers over Redis-backed buses (`scarlets`' `Messenger`/
`Mapper`/`Federator`). A worker never runs its own LLM call to interpret a
dispatched task — by the time the head has decided which skill applies,
the message is already fully structured, so worker-side dispatch is a
plain lookup.

## The `Skill` interface

A `Skill` is the unit of capability. Every skill implements two methods:

```python
class Skill(ABC):
    name: str
    description: str

    def contribute(self, ctx, request) -> None:
        """Runs on every worker asked to participate. Does local compute,
        publishes results via Mapper/Federator. No return value — the
        result surfaces through those primitives, not a call stack,
        since contribute() and coordinate() run in different processes."""

    def coordinate(self, ctx, request, workers) -> dict:
        """Runs on exactly one agent — the coordinator. Gathers
        contributions and returns the final, JSON-serializable result."""
```

Which agent coordinates is decided per-invocation by `coordinator_for()`,
which **defaults to a random worker, never the head** — the head controls
task *routing*, not where computation happens, so it isn't a bottleneck
for every skill's aggregation step under concurrent invocations.

New capabilities are added by dropping a new module under `skills/` — the
harness discovers it automatically (`skills/registry.py`) and dispatch
logic never changes. Reference skills already included:

| Skill | Shape |
|---|---|
| `median` | Not associative — needs the full partitioned data and a real merge. Backed by `Mapper.AllGather()`. |
| `sum` | Associative reduction, backed by `Federator`. Parameterized (`transform: identity\|square`); combined with `combine`, enough to derive variance without a dedicated skill. |
| `combine` | Local, non-distributed arithmetic over an AST-whitelisted expression — closes the composition loop without a skill per formula. |
| `create_scarlet` | A worker mints a new scarlet mid-task via its own LLM reasoning, invocable by any agent, not just the head. |
| `query_feature` / `list_tags` | Edge-local data-source lookup — see [Local-First Data Access](#local-first-data-access) below. |

## Talking to the harness: `converse()`

The head's LLM tool-calling loop (`head.converse()`) turns free text into
zero or more skill invocations plus a final reply, dispatching multiple
tool calls in one turn concurrently when the model asks for them (e.g. two
`sum` calls needed to derive a variance). A timeout doesn't fall straight
to a mechanical retry: when an `AgentDialogue` and LLM client are wired in,
the head has a real check-in conversation with the coordinator first,
grounded in the coordinator's own live state, and only retries if that
conversation actually concludes the work is stuck.

## Agent-to-agent dialogue

`AgentDialogue` generalizes the same "narrate, decide, respond" loop to
run between any two agents, not just human-and-head — the mechanism a
worker uses to ask a peer something in natural language (e.g. "does anyone
have Roll Speed for equipment 1234") and get a grounded answer back. A
responder's reply is never free-floating narration: an optional
`context_fn`, called fresh before every reply, grounds it in that agent's
own real, current state.

## Local-first data access

Centralizing data-source credentials in one place fights how industrial
sites actually operate. `local_config.py` reads a site-owned
`~/.scarlet/config.yaml` — a plant engineer hand-authors it, and it's the
*primary* mechanism for a worker's own data sources; composer-api's
centralized broker registry still exists, but only for genuinely
centralized sources, not as the default path. There's deliberately no
push path from the operator UI into this file.

Each entry declares a `name`, connector `type`, `mode` (`local`, a direct
in-process connection, or `broker`, relayed through composer-api), and a
natural-language `description` — the same role a scarlet's own description
plays, fed into agent context so a peer can recognize what a source
actually contains.

Two ways an agent finds the right source:

- **`query_feature` / `list_tags` skills** — a worker checks its own local
  config by name, or lists what it has, when it already knows what to ask
  for.
- **On-request tag discovery via `AgentDialogue`** — a worker asking a peer
  "does anyone have `roll_speed`" and a peer replying "I have
  `RollSpeed_1234`, that's probably it" is ordinary dialogue grounded by
  `context_fn`, not a separate protocol. This is how a requester finds a
  tag it doesn't already know the exact name of, without ever needing to
  know what connector or database backs it.

## Resilience

Two mechanisms worth knowing before extending a skill:

- **Retry** — `run_skill()` retries with a fresh coordinator when a result
  is marked `"retryable": True` (transient failures only; a skill's own
  logical errors, like a bad `combine` expression, are not retryable by
  default).
- **Cancellation** — a superseded attempt's workers are told to stop via
  `skill_cancel` before a retry starts, so a worker doesn't keep
  coordinating a computation the head has already moved on from.
