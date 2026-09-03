# scarlet-agentic-harness

A generalized decentralized agentic **Skill** harness built on top of this
repo's `scarlets` primitives (`Mapper`, `Federator`, `Messenger`) — deployed
alongside [Gustavo](https://github.com/disys-lab/gustavo). Lives in this
monorepo at `harness/`, built as `ghcr.io/disys-lab/scarlet-agents` (see
[Deployment](deployment.md)).

## What this is

Scarlet Composer Studio gives agents shared memory and messaging over Redis.
It does not define what an agent's *task* looks like — that's what this
component adds: a **Skill** interface (`scarlet_agentic_harness/skills/base.py`)
that any well-defined distributed computation implements, plus a thin,
skill-agnostic harness that dispatches invocations across a head and any
number of worker agents using only scarlets primitives — no side channels.

Three reference skills exist, deliberately chosen to exercise different shapes:

- **`median`** — workers each hold a private, unordered list of numbers; the
  head assigns one worker as coordinator (workers never self-assign); the
  coordinator gathers every worker's sorted local partition via
  `Mapper.AllGather()` and merges them into the true global median. Median
  isn't an associative reduction (you can't combine two workers' local
  medians into the global one), so it can't be built on `Federator` at all —
  it needs the full partitioned data and a real merge.
- **`sum`** — the first `Federator`-backed skill, and the first to take a
  parameter (`transform: identity|square`). `Federator` *is* built for
  associative reductions, but the coordinator is still a randomly-assigned
  worker, same as median — nothing about `Federator` requires centralizing
  on the head. Reports both the total and `n` (total element count across
  all workers, co-aggregated as one numpy array in a single `Aggregate()`
  call, not `len(workers)` — those are different numbers). `sum(transform=
  identity)` and `sum(transform=square)`, plus `n`, are enough to derive
  mean/variance/stddev from pure arithmetic with no new skill and no new
  distributed protocol — `tests/test_sum_skill.py` proves this concretely.
- **`combine`** — the local, non-distributed arithmetic step that closes the
  composition loop: it evaluates a model-supplied expression (e.g.
  `"s2/n - (s1/n)**2"`) against model-supplied named variables via
  `safe_eval` (an AST-whitelisted evaluator — numeric constants, variable
  lookup, `+ - * / **`, unary `+/-` only; everything else, including any
  function call or attribute access, is rejected before anything runs).
  Deliberately generic rather than a `CombineVarianceSkill` with the formula
  baked in — that defeats the whole point of a small composable skill
  library.

Together these prove the `Skill` interface generalizes past "head aggregates
centrally", past "every skill needs `Mapper`", and past "every skill is
distributed" — a new skill is a new module under `skills/`, never a change
to `head.py`/`worker.py`'s dispatch logic. Two production skills also exist:
`create_scarlet` (mint a new scarlet mid-task via LLM reasoning) and
`query_feature` (tag-level, edge-local data-source lookup — see
[Data Sources](../composer/data-sources.md) for the composer-side registry
this complements).

See [Status](status.md) for the detailed build history and test coverage,
and [Design Decisions](design.md) for the architectural choices worth
knowing before extending this harness.
