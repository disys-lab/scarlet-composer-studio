# Contributing a Skill

Instructions for adding a new skill to the scarlet agentic harness,
written to be followed by a coding agent (Claude Code, OpenCode, Cursor)
as well as by a person.

A skill is one well-defined distributed computation the head can offer to
a human and delegate across workers. Adding one requires **no changes to
dispatch, the head, or any existing skill**.

---

## If you are an agent: do exactly this

This document is long. This section is the whole job in order. Follow it
top to bottom; the numbered sections below are reference for each step.

```
1  Decide compound or core.                       -> §2
   Almost every statistic is COMPOUND. If it is
   "agree columns, reduce, do arithmetic", it is
   compound and you write NO dispatch code.

2  Name it.                                       -> §1a
   class = PascalCase skill name + "Skill".
   rms -> RmsSkill.  t_test -> TTestSkill.

3  Write the skill.                               -> §2a
   COPY the plan skeleton. Check the step table
   in §2a for what each step RETURNS - do not
   guess field names.

4  Write the tests.                               -> §5
   COPY the harness verbatim. Do not write your
   own fixture. There are no custom pytest
   fixtures in this repo - if you write
   `def test_x(skills)` it will not run.
   At least ONE test must let `combine` and
   `distribution` run for real and compare the
   number against scipy. Tests that stub every
   step have passed against a skill that could
   not run at all.

5  Write the notebook.                            -> §6
   COPY notebook 15 and change four cells.

6  RUN IT.                                        -> §7
   Not optional. See below.
```

### The four commands that decide whether you are done

Writing the files is step 5 of 7. You are not finished until these four
have run and you have read their output.

**Set your environment up once**, exactly as `harness/README.md` says -
that is the authoritative path and this guide does not restate it. It is
a virtualenv on Python 3.11-3.13, `scarlets` installed from this repo
rather than PyPI, and `composer-api` on `PYTHONPATH`. Docker must be
running, because the integration tests start throwaway Redis and Postgres
containers.

**Run the tests on your machine, not inside the agent image.** Commands 0
and 2 below are plain pytest for that reason. Wrapping them in
`docker run` looks like it should work and silently disables 34 of them:
`conftest.py` publishes Redis to a host port and connects to
`127.0.0.1`, which from inside a sibling container reaches nothing. That
mistake was in this guide for a while, and the resulting errors read as
normal.

Command 1 **is** a `docker run`, on purpose - it is the only one asking a
question about the image, and it needs the image built (§7 step 4).

```bash
# 0. the conformance suite - the cheapest signal, and it finds your skill
#    by itself. Every rule in §2a is checked here; each failure names its
#    own fix. Run this one FIRST and after every edit.
python -m pytest harness/tests/test_compound_skill_conformance.py -q

# 1. your skill is in the image and registered. This one is a container
#    on purpose: it asks what the FLEET will see, not what your working
#    tree holds. If your skill is missing here, the image is stale -
#    rebuild it (§7 step 4).
docker run --rm ghcr.io/disys-lab/scarlet-agents:local python -c \
  "from scarlet_agentic_harness.skills.registry import discover_skills; print(sorted(discover_skills()))"

# 2. your tests - and everyone else's - pass
python -m pytest harness/tests/ -q

# 3. your notebook runs against a live fleet and prints the right number
docker exec scarlet-notebooks-jupyter sh -c \
  "cd /notebooks && jupyter nbconvert --to notebook --execute --inplace \
   --ExecutePreprocessor.timeout=800 <NN>_<name>.ipynb"
```

**What a green run looks like.** Measured:

```
with LLM endpoint  497 passed,  0 skipped, 1 failed
no LLM endpoint    478 passed, 15 skipped, 1 failed  (+0-4 flaky errors)
```

The 15 skips are the multi-process tests - separate OS processes, a live
bus, cancellation, concurrency. Every skill generates its worker-local SQL
with a model, so they cannot run without one. Set `LLM_BASE_URL`,
`LLM_API_KEY` and `LLM_MODEL` to turn them on.

**One known failure**, inherited:

```
test_query_data_source.py::...brokers_real_result
    The broker answers 404. Both sides agree the route is /query, so the
    registered broker_url is probably pointing at the composer-api port.
```

**And one known flake**: `conftest.py`'s Postgres fixture sometimes runs
`psql` before the server is really ready and dies with exit 2, taking
4 tests with it (list_tags, query_feature, tag_cache_resilience x2). Its
readiness check passes too early. Re-running usually clears it; that is a
bug, not a workflow.

**Diff against this before you start.** Anything else is yours.

```bash
# 0. the conformance suite - the cheapest signal, and it finds your skill
#    by itself. Every rule in §2a is checked here; each failure names its
#    own fix. Run this one FIRST and after every edit.
python -m pytest harness/tests/test_compound_skill_conformance.py -q

# 1. your skill is in the image and registered. This one is a container
#    on purpose: it asks what the FLEET will see, not what your working
#    tree holds. If your skill is missing here, the image is stale -
#    rebuild it (§7 step 4).
docker run --rm ghcr.io/disys-lab/scarlet-agents:local python -c \
  "from scarlet_agentic_harness.skills.registry import discover_skills; print(sorted(discover_skills()))"

# 2. your tests - and everyone else's - pass
python -m pytest harness/tests/ -q

# 3. your notebook runs against a live fleet and prints the right number
docker exec scarlet-notebooks-jupyter sh -c \
  "cd /notebooks && jupyter nbconvert --to notebook --execute --inplace \
   --ExecutePreprocessor.timeout=800 <NN>_<name>.ipynb"
```

**What a green run looks like.** Measured on the path above:

```
no LLM endpoint    482 passed, 15 skipped, 1 failed
with LLM endpoint  491 passed,  0 skipped, 7 failed
```

The 15 skips are the multi-process tests - separate OS processes, a live
bus, cancellation, concurrency. Every skill now generates its worker-local
SQL with a model, so they cannot run without one. Set `LLM_BASE_URL`,
`LLM_API_KEY` and `LLM_MODEL` to turn them on.

The remaining failures are inherited, not yours:

```
test_query_data_source.py::...brokers_real_result   broker returns 404
test_scarlet_registration.py (x2)                   stale: asserts 'sum'
                                                    where the prompt now
                                                    says 'sum_core'
test_worker_cancellation.py                         worker comes up with
                                                    no profiled source
test_real_llm_median.py                             per-column result
test_sum_skill.py                                   per-column result
```

**Diff against this list before you start.** A failure not on it is
yours. Do not treat a non-zero exit as normal - treat anything *new* as
yours.

```bash
# 0. the conformance suite - the cheapest signal, and it finds your skill
#    by itself. Every rule in §2a is checked here; each failure names its
#    own fix. Run this one FIRST and after every edit.
python -m pytest harness/tests/test_compound_skill_conformance.py -q

# 1. your skill is in the image and registered. This one is a container
#    on purpose: it asks what the FLEET will see, not what your working
#    tree holds. If your skill is missing here, the image is stale -
#    rebuild it (§7 step 4).
docker run --rm ghcr.io/disys-lab/scarlet-agents:local python -c \
  "from scarlet_agentic_harness.skills.registry import discover_skills; print(sorted(discover_skills()))"

# 2. your tests - and everyone else's - pass
python -m pytest harness/tests/ -q

# 3. your notebook runs against a live fleet and prints the right number
docker exec scarlet-notebooks-jupyter sh -c \
  "cd /notebooks && jupyter nbconvert --to notebook --execute --inplace \
   --ExecutePreprocessor.timeout=800 <NN>_<name>.ipynb"
```

**Known failures on a fresh clone.** Command 2 does not reach zero.
Measured: **479 passed, 9 failed, 4 errors, 6 skipped**. Every one of the
13 is pre-existing. They rotted during a period when this guide told
everyone to run the suite inside a container, where they could not run at
all and their errors read as normal.

```
test_sum_skill.py::test_sum_identity_and_square_and_variance_composition
test_variance_composition_end_to_end.py::test_variance_via_two_sums_and_a_combine
    "'sum' is a compound skill but no skill registry was passed to
    run_skill" - written before `sum` became compound.

test_scarlet_registration.py::test_sum_dispatch_preregisters_both_federator_scarlets_with_llm_description
test_scarlet_registration.py::test_median_dispatch_preregisters_one_mapper_scarlet_without_llm
    patch `head.register_scarlet_definition`, refactored away since.

test_median_skill.py::test_median_across_three_worker_processes
test_converse_end_to_end.py::test_converse_drives_a_real_median_computation
test_worker_cancellation.py::test_skill_cancel_stops_a_stuck_coordinate_call_quickly
test_worker_concurrency.py::test_two_concurrent_invocations_on_the_same_coordinator_both_succeed
    spawn real worker subprocesses; the workers come up with no profiled
    local source ("choose_source returned None").

test_list_tags_skill.py, test_query_feature_skill.py, test_tag_cache_resilience.py (x2)
test_query_data_source.py::test_query_data_source_authenticates_and_returns_the_brokers_real_result
    need a live broker / data-source fixture.
```

**Diff against this list before you start.** A failure not on it is
yours; one on it is inherited. Do not treat a non-zero exit as normal -
treat anything new as yours.

Paste the real output of each into your final report. If you have not run
them, say so plainly rather than describing the files you wrote.

**"Syntactically correct" is not a result.** Three things have gone wrong
here before, every one of them invisible until something was executed: a
test file that could not collect, a plan whose two branches were
identical so the answer was always 1.0, and a statistic that was
self-consistent and wrong. None of those look wrong on the page.

---

## Pointing your agent at this guide

From a clone of the repository:

```
> read docs/AGENTS.md and add a skill that computes <X>
```

Claude Code and OpenCode both read repository files directly, so naming
the path is enough. Keep this file in context for the whole task - the
contract in §2 and the checklist in §8 are the parts most often skipped.

If your agent supports project-level instructions, add:

```
When adding a harness skill, follow docs/AGENTS.md exactly.
Run the tests in §7 before claiming the skill works.
```

---

## 1. What you must deliver

A contribution is **not** just a skill file. All five, or it will be sent
back:

| # | Artifact | Path |
|---|---|---|
| 1 | The skill | `skills/compound/<name>.py` if compound, `skills/core/<name>.py` if core — see §2 |
| 2 | Its tests | `harness/tests/test_<name>_skill.py` |
| 3 | A test-data generator | `harness/tests/data/make_<name>_data.py` |
| 4 | A notebook | `docker/jupyter/notebooks/<NN>_<name>.ipynb` |
| 5 | Stated limitations | A `Limitations` section in the skill's module docstring |

---

## 1a. Fix your interface before writing anything

You will write several files that have to agree with each other. Decide
these three things first, write them in the skill's module docstring, and
do not change them afterwards. Every later file copies from there.

**1. The class name is the skill name in PascalCase, plus `Skill`.**
No exceptions - the test has to import it without guessing.

| `name` | class |
|---|---|
| `rms` | `RmsSkill` |
| `z_test` | `ZTestSkill` |
| `chi2_test` | `Chi2TestSkill` |

**2. The result contract.** Write the exact keys you return:

```
Returns
-------
{"status": "ok", "result": <list of float, per column>,
 "columns": <list of str>, "n": <int>}
```

Always include `n` if your result is an average of anything. A caller
cannot judge a mean without knowing how many values are behind it, and
cannot compose with you without it.

**3. Required vs optional parameters.** Anything in `required` must be
checked before use, and a missing one is a returned error, not a crash.

This is not ceremony. The most common way a contribution fails here is two
files that each look correct and disagree with each other - a skill
defining `ZTest` and a test importing `ZTestSkill`, so eight tests fail on
an import error before a line of the computation runs.

---

## 2. First decide: compound, or core?

**Answer this before writing anything. Most new skills are compound, and
writing a core skill when a compound would do is the most common mistake
made here.**

```
Can your computation be expressed as:
  "agree the columns, reduce over them, then do arithmetic on the result"?
                    │                                    │
                   YES                                   NO
                    │                                    │
                    ▼                                    ▼
          Write a COMPOUND skill.              Write a CORE skill.
          A plan. No dispatch code.            §3. You will need the
          No Federator. No readiness           Federator/readiness
          handshake. Go to §2a.                plumbing. Go to §2b.
```

Almost every **statistic** is compound. Mean, variance, standard
deviation, z-score, t-statistic, coefficient of variation, standard
error, RMSE - all of them are "sum something, then divide". If you find
yourself writing `ctx.federator(...)` for a statistic, stop and re-read
this section.

You need a **core** skill only when the computation is not a sum:

- it is not associative (median, quantiles, mode) - needs all the data
- it reduces with something other than addition (min, max, bitwise)
- it is not a reduction at all (querying, listing, minting)

### 2a. Writing a compound skill

A `CompoundSkill` is a plan over skills that already exist. There is no
`contribute`, no `coordinate`, no Mapper, no Federator - the plan runner
does all of it.

```python
from scarlet_agentic_harness.skills.base import CompoundSkill, Step
from scarlet_agentic_harness.skills import predicate


class ZScoreSkill(CompoundSkill):
    name = "z_score"
    description = (
        "One-sample z-test of the fleet's measurements against a "
        "hypothesised mean. Returns z per column. Use when sigma is known."
    )
    parameters = {
        "type": "object",
        "properties": {
            "mu0": {"type": "number", "description": "Hypothesised mean."},
            "sigma": {"type": "number",
                      "description": "Known population standard deviation."},
            "objective": {"type": "string",
                          "description": "What to measure, in plain language."},
            "columns": {"type": "array", "items": {"type": "string"}},
            # Always reuse this - never hand-write a conditions schema.
            # It is the row filter, a LIST of {column, op, value}, and a
            # hand-written `{"type": "object"}` makes the head unable to
            # pass one.
            "conditions": predicate.CONDITIONS_SCHEMA,
        },
        "required": ["mu0", "sigma"],
    }
    plan = [
        Step("agree_representation", produces={"columns": "result"}),
        Step("sum_core", produces={"s1": "result", "n": "n"}),
        Step("combine",
             params={"expression": "(s1/n - mu0)/(sigma/(n**0.5))",
                     "variables": {"s1": "$s1", "n": "$n",
                                   "mu0": "$mu0", "sigma": "$sigma"}},
             produces={"z": "result"}),
    ]
    returns = {"result": "z", "columns": "columns", "n": "n"}
```

That is a complete, working skill. Note what is **not** there.

How the plan runs:

- The namespace starts as your params, so `$mu0` and `$sigma` resolve from
  what the caller passed. You do not plumb them anywhere.
- Each `Step`'s `produces` maps *your* namespace name to a *field of that
  step's result*: `{"s1": "result", "n": "n"}` means "bind `s1` from the
  step's `result`, and `n` from its `n`".
- `$name` in `params` resolves from the namespace at dispatch time.
- A step whose outputs are all already bound is **skipped** - which is how
  `variance` nests `mean` and still runs consensus only once.
- A failed step aborts the plan, carrying its `retryable` upward.

### The steps you can compose, and what they return

`produces` maps **your namespace name** to **a field of that step's
result**. The direction is `{"your_name": "their_field"}`, and
`their_field` must actually exist - inventing one silently binds `None`.

| Step | Useful `params` | Result fields you can bind |
|---|---|---|
| `agree_representation` | `objective` | `result` (the agreed column list), `proposals`, `objections` |
| `sum_core` | `transform` (`identity` or `square`), `columns`, `conditions`, `workers` | `result` (per-column sums), `n` (element count), `columns` (width), `empty_workers` |
| `median` | `columns`, `conditions`, `workers` | `result`, `columns` |
| `combine` | `expression`, `variables` | `result` |
| `distribution` | `dist` (`norm`/`t`/`chi2`/`f`), `method` (`sf`/`cdf`/`pdf`/`ppf`), `x`, `params` (`df`, or `dfn`+`dfd` for `f`) | `result` |

So the agreed columns are bound with `produces={"columns": "result"}` -
**not** `{"columns": "columns"}`. And a sum of squares is:

```python
Step("sum_core", params={"transform": "square"},
     produces={"s2": "result", "n": "n"}),
```

Without `params={"transform": "square"}` you get Sigma(x), not Sigma(x^2),
and the answer is wrong rather than broken - nothing will tell you.

### Comparing two subsets in one plan

A step's own `params` **override** the ambient namespace. That is how you
run the same statistic over two different slices of the fleet and compare
them - a two-sample test, a before/after, a per-site comparison:

```python
plan = [
    Step("agree_representation", produces={"columns": "result"}),
    # Same skill, twice, narrowed differently. The step's `workers`
    # overrides whatever the caller passed.
    Step("variance", params={"workers": "$group_a"},
         produces={"var_a": "result", "n_a": "n"}),
    Step("variance", params={"workers": "$group_b"},
         produces={"var_b": "result", "n_b": "n"}),
    Step("combine", params={"expression": "var_a/var_b",
                            "variables": {"var_a": "$var_a", "var_b": "$var_b"}},
         produces={"f": "result"}),
    Step("distribution",
         params={"dist": "f", "method": "sf", "x": "$f",
                 "params": {"dfn": "$n_a", "dfd": "$n_b"}},
         produces={"p_value": "result"}),
]
returns = {"result": "f", "p_value": "p_value", "columns": "columns",
           "n_a": "n_a", "n_b": "n_b"}
```

Narrow with `workers` to compare agents, or with `conditions` to compare
row ranges on the same agents. Either way **each step must say how it
differs** - and the outputs must bind to *different* namespace names.

This is the single easiest thing to get wrong here. An earlier
contribution declared a `group_column` parameter, then wrote two identical
steps that referenced it nowhere:

```python
Step("mean", produces={"mean_group1": "result", "n_group1": "n"}),
Step("mean", produces={"mean_group2": "result", "n": "n"}),   # identical
```

Both computed the same number over the whole fleet, so the ratio was
always exactly 1.0. It dispatched, returned, and looked entirely
plausible. **A declared parameter that no step consumes does nothing** -
if your plan takes a parameter, some step's `params` must reference it.

Four rules that are not optional:

- **`returns` must re-export everything a caller needs**, not just the
  headline number. Returning `z` but dropping `n` leaves the caller unable
  to compose with you or to sanity-check the result. This has been got
  wrong twice in this repo.
- **Declare every parameter in `parameters`, including `conditions` and
  `workers`.** Propagation into steps is automatic, but the head never
  sends a parameter your schema does not mention - so a filtered question
  silently returns the unfiltered answer, and a question about one worker
  silently returns the fleet-wide one.

  Measured live: asked for a z-test on worker1's data, `z_test` - which
  declared `conditions` but not `workers` - returned `n=387`, the whole
  fleet, and `z=0.888471` instead of worker1's `0.746779`. It reached the
  same conclusion, which is precisely why nobody noticed. Five skills had
  the same gap. If your plan contains `sum_core`, `sum`, `mean`, `median`
  or `variance`, it reduces over the fleet and needs both parameters;
  the conformance suite now fails you if they are missing.
- **`combine` is arithmetic only**: `+ - * / **`. No function calls at
  all, so there is no `sqrt` - write `n**0.5`.
- **Every name in an expression must be bound in that step's
  `variables`.** An unbound name is `unknown variable` on the first
  dispatch, and the plan aborts there.

`tests/test_compound_skill_conformance.py` checks all of these against
every registered compound, automatically - you wire nothing up, you write
the skill and it is checked. Run it first; it is the fastest signal
available and each failure names its own fix.

#### Arithmetic when there are no functions to call

The two you will reach for are spelled with exponents:

| What you want | How it is written |
|---|---|
| `sqrt(x)` | `x**0.5` |
| `abs(x)` | `(x**2)**0.5` |

You will need the second one. **`sf` is the UPPER tail only**, and for a
symmetric distribution (`norm`, `t`) the statistic can be negative:
`sf(-0.31)` is `0.62`. A plan that writes a two-sided p-value as
`2*sf(t)` therefore reports **1.75** for that input - not a probability.
Nothing raises; it is ordinary arithmetic on a real number, and a fixture
whose statistic happens to be positive never shows it. Take the magnitude
first:

```python
Step("combine", params={"expression": "(t**2)**0.5",
                        "variables": {"t": "$t"}},
     produces={"abs_t": "result"}),
Step("distribution", params={"dist": "t", "method": "sf", "x": "$abs_t",
                             "params": {"df": "$df"}},
     produces={"p_one_sided": "result"}),
Step("combine", params={"expression": "2*p_one_sided",
                        "variables": {"p_one_sided": "$p_one_sided"}},
     produces={"p_value": "result"}),
```

`chi2` and `f` statistics cannot be negative, so their upper tail is
already the one-sided p-value and none of this applies.

#### Conditional steps: `when`

A step runs only if its `when` matches the namespace. This is RULE 0, and
it is checked before RULE 1, so a conditional *check* step obeys its
condition too:

```python
Step("combine", when={"mode": "upper"}, ...)
Step("combine", when={"mode": ["upper", "two-sided"]}, ...)   # list = any of
```

Every entry must match. A list matches membership. A variable the
namespace does not hold **never** matches, so a condition on a name
nothing sets is a skip, not a guess — which is why a parameter you branch
on must declare a `default` in your schema. `PlanRunner` seeds the
namespace with declared defaults before the first step; without one, a
plan branching on an omitted parameter runs *no* branch and returns
nothing.

Several steps may bind the same output under mutually exclusive
conditions. Exactly one runs, the plan stays linear, and the branch is
visible in the plan rather than buried in an expression.

#### A hypothesis test returns the statistic AND the p-value

If your skill is named `*_test`, its plan must contain a `distribution`
step and its `returns` must carry both `result` (the statistic) and
`p_value`. The conformance suite enforces both.

A statistic on its own does not answer "is this significant?", and
leaving the conversion to the head goes wrong in two measured ways. It
forgets: asked to "run a z test on vibration_rms", the head returned a
bare z and stopped, and only an explicit "give me the p-value" produced
one. Or it improvises: asked for a chi-squared test, it once answered
"the standardized z-score is approximately -4.444, so P(Z > -4.444) is
approximately 1" - a tail probability recalled from memory rather than
computed.

**And it must offer all three tails.** This is not optional: a `*_test`
skill declares

```python
"mode": {"type": "string",
         "enum": ["two-sided", "upper", "lower"],
         "default": "two-sided"},
```

and ends with this block, which is deliberately identical in every
hypothesis test in the package:

```python
Step("distribution",
     params={"dist": D, "method": "sf", "x": "$stat", "params": {...}},
     produces={"p_upper": "result"}),
Step("combine", when={"mode": "upper"},
     params={"expression": "p_upper", "variables": {"p_upper": "$p_upper"}},
     produces={"p_value": "result"}),
Step("combine", when={"mode": "lower"},
     params={"expression": "1 - p_upper", "variables": {"p_upper": "$p_upper"}},
     produces={"p_value": "result"}),
Step("combine", when={"mode": "two-sided"},
     params={"expression": "1 - ((2*p_upper - 1)**2)**0.5",
             "variables": {"p_upper": "$p_upper"}},
     produces={"p_value": "result"}),
```

Only `dist` and its shape parameters change. Copy it.

Two things make this work. `sf` is always the upper tail, so `1 - u` is
always the lower one. And the two-sided expression is the identity

```
2*min(u, 1-u)  ==  1 - |2u - 1|
```

which holds for **every** distribution here, symmetric or not - verified
to 5.6e-17 against norm, t, chi2 and f. That is why no separate
`|statistic|` step is needed: the sign is handled for you.

**Why all three, rather than picking one.** A hard-coded tail answers a
different question from the one asked, and does it silently. A two-sided
p-value used for "is the variance greater than 1?" is twice what it
should be; an upper tail used for "do these differ?" is half. Both come
back looking like perfectly ordinary probabilities. The conformance suite
fails any `*_test` that does not declare the parameter, default to
two-sided, and carry one mutually exclusive branch per mode - and it
evaluates each branch's expression to check it computes the tail it
claims.

Existing compounds to copy from: `skills/compound/mean.py`,
`skills/compound/variance.py`, and `skills/compound/t_test.py` for a
statistic together with its p-value.

### 2b. The core-skill contract

```python
from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.skills.base import Skill


class MySkill(Skill):
    name = "my_skill"                 # dispatch key and LLM tool name
    description = "..."               # the LLM reads this to decide when to call it
    parameters = {                    # JSON Schema for the tool call
        "type": "object",
        "properties": {...},
        "required": [],
    }
    coordinate_timeout = 15.0         # seconds coordinate() waits for peers

    def contribute(self, ctx: HarnessContext, request: dict) -> None:
        """Runs on EVERY worker asked to participate. Returns nothing."""

    def coordinate(self, ctx: HarnessContext, request: dict,
                   workers: list[str]) -> dict:
        """Runs on ONE agent. Returns the final JSON-serialisable result."""
```

Rules that are not negotiable:

- **`contribute` returns nothing.** It runs in a different process from
  `coordinate`. Results travel through `Mapper`/`Federator`, never a call
  stack.
- **`coordinate` returns a dict** with `"status": "ok"` or
  `"status": "error"`. An error must carry `"detail"` and `"retryable"`.
- **Prefer a returned error over a raise, in `coordinate`.** Both halves
  are wrapped by the worker, so a raise is caught and reported - it does
  not hang the head. But the head then sees
  `failed during coordinate of 'z_test': KeyError: 'sigma'`, which says
  what blew up and not what the caller did wrong. Read params with
  `.get()` and return a message the caller can act on:

  ```python
  mu0 = request["params"].get("mu0")
  if mu0 is None:
      return {"status": "error", "retryable": False,
              "detail": "missing required parameter 'mu0'"}
  ```

- **`contribute` has no return value**, so it cannot report an error that
  way. It has two options:
  - **raise** - the worker catches it, sends a `skill_result` error naming
    the stage, and re-raises so the traceback still reaches stderr. Fine
    for genuinely unexpected failures.
  - **signal it in the readiness message** - the right choice when the
    coordinator needs to distinguish *this worker failed* from *this
    worker had nothing*. `sum_core` carries `map_status` and `map_error`
    for exactly this, and the coordinator turns a false `map_status` into
    a retryable error for the whole round.

  Note that a raise in `contribute` is reported with `retryable: False`.
  If the failure is transient and worth retrying, say so through the
  readiness message rather than raising.
- **Never compute on the head.** `coordinator_for()` defaults to a random
  worker; do not override it unless aggregation is trivially cheap.
- **`description` is a prompt.** The LLM decides whether to call your
  skill from this string alone. Say what it computes and when to use it.

### Which primitive

| Your computation | Use |
|---|---|
| Associative (sum, count, min) | `Federator` via `ctx.federator(...)` |
| Needs all the data (median, quantiles) | `Mapper.AllGather()` |
| Purely local arithmetic | Neither - see `combine.py` |

If you use a `Mapper` or `Federator`, implement `scarlet_names()` so the
names get pre-registered with real descriptions. It is a **method on your
skill** returning a **list of strings** - the concrete Redis keys your
skill will construct:

```python
def scarlet_names(self, mapper_name: str) -> list[str]:
    # Must match what Federator.__init__ actually constructs.
    return [f"{mapper_name}_mapper_reducer", f"{mapper_name}_mapper_global"]
```

### Worked example: the two halves of an associative skill

Do not guess these call shapes. Contributors `Map` their partial result
and then signal readiness on the **local** bus; the coordinator counts
those signals and only then `Aggregate`s. There is no blocking `collect()`.

The imports are part of the contract - these are the real module paths,
and they are not guessable:

```python
import numpy as np
from scarlets.core.Mapper import Mapper          # NOT from scarlet_agentic_harness
from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.skills.base import Skill
from scarlet_agentic_harness import local_matrix
```

```python
_READY = "my_skill_contribution_ready"      # module-level, unique per skill

def contribute(self, ctx, request):
    matrix, meta = local_matrix.load_local_matrix(ctx, objective, columns=..., conditions=...)
    contribution = np.array([matrix.sum(axis=0), [matrix.shape[0]] * matrix.shape[1]])

    federator = ctx.federator(request["mapper_name"], op=Mapper.SUM)
    _, ok, exc = federator.Map(contribution, key=ctx.agent_id)

    ctx.buses.local_bus.Send(request["coordinator"], {
        "type": _READY, "request_id": request["request_id"],
        "from": ctx.agent_id, "ncols": int(matrix.shape[1]),
        "map_status": bool(ok), "map_error": str(exc) if exc else None,
    })

def coordinate(self, ctx, request, workers):
    ready, ncols = set(), set()
    deadline = self.staggered_deadline(len(workers))
    while len(ready) < len(workers) and deadline.still_waiting(len(ready)):
        msg = ctx.buses.local_router.receive_for(request["request_id"], timeout=1)
        if not msg:
            continue
        body = msg.get("body", {})
        if body.get("type") == _READY:
            ready.add(body["from"])
            ncols.add(int(body["ncols"]))

    missing = set(workers) - ready
    if missing:
        return {"status": "error", "retryable": True,
                "detail": f"workers did not report ready in time: {sorted(missing)}"}

    federator = ctx.federator(request["mapper_name"], op=Mapper.SUM)
    totals, ok, exc = federator.Aggregate(np.zeros((2, next(iter(ncols))), dtype=float))
    ...
```

Three things in there that are easy to get wrong:

- `ctx.federator(name, op=...)` and `ctx.mapper(name, description=...)` -
  the name must be `request["mapper_name"]`, which is unique per request.
- `Map` and `Aggregate` each return a **three-tuple**
  `(value, ok, exception)`. Ignoring `ok` hides a failed write.
- `Aggregate(identity)` folds onto whatever you seed it with, and the
  coordinator's own contribution is already included. Seed with the
  identity element - zeros - or you double-count it.

### Reaching local data

Never accept a file path. The head states an objective; the worker
resolves its own source:

```python
matrix, meta = local_matrix.load_local_matrix(
    ctx,
    request["params"].get("objective", "all available numeric measurements"),
    columns=request["params"].get("columns"),
    conditions=request["params"].get("conditions"),
)
```

Accept `columns` and `conditions` if your skill aggregates. `columns`
comes from `agree_representation`; `conditions` is the row filter, and
every worker must apply exactly the same one.

---

## 3. Registration

There is none. `skills/registry.py` walks the package and finds any
`Skill` subclass. Drop the file in `skills/core/` and it is live.

Two consequences:

- Your module must import cleanly with no side effects at import time.
- Give the class a unique `name`. A collision silently shadows.

---

## 4. The test-data generator

Tests must not depend on data that happens to be lying around. Write
`harness/tests/data/make_<name>_data.py` that generates it:

```python
"""Generate deterministic test data for <name>."""
import numpy as np, pandas as pd

def make(path, rows=100, seed=0):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=rows, freq="min"),
        "value": rng.normal(100, 15, rows),
    })
    df.to_csv(path, index=False)
    return df
```

Requirements:

- **Seeded.** The same seed gives the same data, so a failure reproduces.
- **Returns the frame**, so a test can compute the expected answer from
  the same data rather than hardcoding a number.
- **Realistic shape**: real column names, and missing values where a real
  feed would have them.

---

## 5. The tests

`harness/tests/test_<name>_skill.py`. Follow the existing files -
`test_row_filtering.py` is the clearest model.

Cover at least:

1. **The happy path**, against ground truth computed from the generated
   data - not a hardcoded constant.
2. **Every error branch** your `coordinate` can return, each asserting the
   message says what is wrong.
3. **An edge case specific to your computation** - empty input, one
   worker, all-identical values, whatever would be wrong silently.

```python
def test_result_matches_ground_truth(tmp_path):
    df = make(tmp_path / "d.csv", rows=100, seed=0)
    expected = df["value"].mean()          # from the same data
    ...
    assert result["result"] == pytest.approx(expected)
```

**Do not mock the computation you are testing.** Mock the bus and the
workers; compute for real.

### A fixture that works

Stubbing a distributed skill is the hardest part of this, and getting it
subtly wrong wastes more time than writing the skill did. Copy this.

```python
from types import SimpleNamespace
import numpy as np, pandas as pd, pytest, yaml
from scarlet_agentic_harness import data_profile, local_config


def _ctx(monkeypatch, tmp_path, ready_bodies, aggregate_value):
    """A ctx that drives coordinate() without Redis or a fleet."""
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"value": rng.normal(100, 15, 50)})
    csv = tmp_path / "d.csv"
    df.to_csv(csv, index=False)

    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"sources": [{
        "name": "test_source", "path": str(csv),
        "mode": "local", "type": "csv", "description": "test"}]}))
    monkeypatch.setattr(local_config, "CONFIG_PATH", cfg)

    class _Router:
        def __init__(self): self._q = [{"body": b} for b in ready_bodies]
        def receive_for(self, rid, timeout=1):
            return self._q.pop(0) if self._q else None
        def forget(self, rid): pass

    class _Fed:
        # Aggregate returns a THREE-tuple. Map does too.
        def Aggregate(self, identity): return aggregate_value, True, None
        def Map(self, value, key=None): return None, True, None

    class _Buses:
        local_bus = SimpleNamespace(Send=lambda *a, **k: None)
        local_router = _Router()

    ctx = SimpleNamespace(
        agent_id="w1",
        buses=_Buses(),
        data_profiles=data_profile.profile_sources(),   # a real profile
        llm_client=None,
        cancelled=SimpleNamespace(is_set=lambda: False),
        federator=lambda name, op=None: _Fed(),
        mapper=lambda name, description="": _Fed(),
        report_progress=lambda **kw: None,
    )
    return ctx, df
```

Three mistakes this exists to prevent, all seen in practice:

- **`ctx` must be an object, not a dict.** `local_matrix` reaches
  `ctx.data_profiles`; a dict raises `AttributeError` several frames away
  from the test.
- **`Aggregate` and `Map` return three-tuples.** A stub returning the bare
  value fails with "not enough values to unpack" inside the skill.
- **Feed the readiness bodies your skill expects.** `coordinate` counts
  them; a stub that sends none times out and your test asserts on
  "workers did not report ready in time" instead of on your computation.

And one that is not about the harness at all: **keep the skill's
parameters separate from your generator's.** A test for `sigma <= 0` that
passes its `sigma` into `rng.normal(loc, scale)` crashes in numpy before
the skill is ever called, and the failure looks like a skill bug.

### Testing a compound skill

A compound has no `contribute`/`coordinate` to stub. Drive the plan
directly, as `tests/test_run_plan.py` does: monkeypatch
`dispatch.run_skill` to record its calls and return canned step results,
then call `dispatch.run_plan(skill, params, None, None, on_result, skills)`.

**The trap: supplying a parameter can skip a step.** RULE 2 skips any step
whose outputs are already bound. So a test that passes
`columns=["a","b"]` will see `agree_representation` **not dispatched** -
correctly - and an assertion of "three steps ran" fails against a skill
that is working exactly as designed.

Copy this harness - do not invent pytest fixtures, there are none beyond
pytest's own:

```python
from scarlet_agentic_harness import dispatch
from scarlet_agentic_harness.skills.base import Skill
from scarlet_agentic_harness.skills.compound.my_stat import MyStatSkill


class _Atomic(Skill):
    """Stands in for any step the plan dispatches."""
    name = "atomic"
    def contribute(self, ctx, request): pass
    def coordinate(self, ctx, request, workers): return {"status": "ok"}


def _registry(*names):
    reg = {}
    for n in names:
        s = _Atomic(); s.name = n; reg[n] = s
    return reg


def _run(skill, params, results, monkeypatch):
    """Run the plan with canned step results; return (final, calls)."""
    calls, box = [], {}

    def fake(step_skill, step_params, config, buses, on_result, **kw):
        calls.append((step_skill.name, step_params))
        on_result(results.get(step_skill.name, {"status": "ok", "result": None}))

    monkeypatch.setattr(dispatch, "run_skill", fake)
    names = [st.skill for st in skill.plan]
    dispatch.run_plan(skill, params, None, None, lambda r: box.update(r),
                      _registry(*names))
    return box, calls


def test_the_plan_computes_the_right_thing(monkeypatch):
    skill = MyStatSkill()
    results = {"variance": {"status": "ok", "result": [4.0], "n": 10},
               "combine": {"status": "ok", "result": [4.0]}}
    final, calls = _run(skill, {"group_a": ["w1"], "group_b": ["w2"]},
                        results, monkeypatch)
    assert final["status"] == "ok"
    assert [name for name, _ in calls][0] == "agree_representation"
```

Note what `_run` returns: the **calls** list is as important as the final
result. Most of what can go wrong in a plan is a step receiving the wrong
params - a missing `transform`, both groups getting the same `workers` -
and only the calls list shows that.

Decide which you are testing and set the params to match:

```python
# Testing the full plan: pass NO columns, so consensus actually runs.
_, calls = run(skill, {"objective": "power"}, ...)
assert [name for name, _ in calls] == ["agree_representation", "sum_core", "combine"]

# Testing the arithmetic: pass columns, and expect consensus to be skipped.
_, calls = run(skill, {"objective": "power", "columns": ["a", "b"]}, ...)
assert [name for name, _ in calls] == ["sum_core", "combine"]
```

That skipping is a feature - it is how `variance` nests `mean` and still
runs consensus once - so assert on it rather than working around it.

### At least one test must let the arithmetic actually run

Everything above stubs `dispatch.run_skill`, which means it stubs
`combine` too - so those tests check the *shape* of each call and never
once evaluate an expression. They agree with the plan by construction.

This is not hypothetical. A contributed `t_test` wrote its statistic as
`(s1/n - mu0)/sqrt(...)`. There is no `sqrt` in `combine`, so the skill
could not run a single time - and all five of its own tests passed,
because not one of them evaluated the expression. Two separate defects
were later found in the same plan the same way.

So stub only the steps that touch worker data, and let `combine` and
`distribution` execute for real:

```python
def _drive_live(skill, params, skills, monkeypatch, s1, s2, n):
    sums = [{"status": "ok", "result": s1, "n": n},
            {"status": "ok", "result": s2, "n": n}]

    class _Ctx:
        agent_id = "test"

    def fake(sk, p, config, buses, on_result, **kw):
        if sk.name in ("combine", "distribution"):
            on_result(sk.coordinate(_Ctx(), {"params": p}, []))   # for real
        elif sk.name == "sum_core":
            on_result(sums.pop(0))            # a queue: it is called twice
        else:
            on_result({"status": "ok", "result": ["value"]})

    monkeypatch.setattr(dispatch, "run_skill", fake)
    box = {}
    dispatch.run_plan(skill, params, None, None, lambda r: box.update(r), skills)
    return box
```

Then assert against a number computed somewhere else entirely.
**Actually run scipy to get it** - do not work the expected value out on
paper. A contributed `proportion_test` hand-computed its expected
p-value as `0.248126198`; the true value is `0.2482130790`, and the skill
it was accusing of being wrong was right. Run the snippet, paste the real
output into the comment:

```python
# scipy.stats.ttest_1samp(XS, 100.0) -> t = 0.3084435454, p = 0.7647647163
assert res["result"] == pytest.approx(0.3084435454, abs=1e-9)
assert res["p_value"] == pytest.approx(0.7647647163, abs=1e-9)
```

**And test a statistic of each sign.** A happy-path fixture with a
positive statistic passes against the `2*sf(t)` bug above; the same
assertion with the hypothesised value on the other side of the mean fails
immediately. The portable version of that check is:

```python
def test_a_negative_statistic_still_gives_a_probability(...):
    assert 0.0 <= res["p_value"] <= 1.0
```

That one holds for every test statistic there is. **Do not copy an
assertion whose premise does not hold for your statistic.** The symmetry
check in `test_t_test_skill.py` - that a hypothesised mean equally far
above and below gives the same two-sided p - is true for a t-test,
because its standard error is estimated from the sample and does not
depend on `mu0`. It is false for a proportion z-test, whose standard
error is `sqrt(p0(1-p0)/n)` and therefore moves with `p0`. Copied across
unchanged, it fails against a skill that is entirely correct. Check that
the maths still applies before reusing an assertion.

See `tests/test_t_test_skill.py` for the whole file.

### Mutation-test your tests

Before you submit: break your skill deliberately - flip a comparison,
drop a term - and confirm a test fails. A test suite that passes against
broken code is worse than none, because it is believed.

Do this to the *live* test above in particular. Changing `x**0.5` to
`x**2`, or `$abs_t` back to `$t`, must turn something red.

---

## 6. The notebook

**Do not write one from scratch.** Copy
`docker/jupyter/notebooks/15_time_window_filter.ipynb`, rename it to the
next free number, and change exactly four things. Everything else -
logging, parameters, data generation, fleet startup, the readiness wait,
teardown - is shared scaffolding that already works and must not be
touched.

The four changes:

1. **The title/intro markdown cell** - what this notebook demonstrates,
   and *what would fail silently* if the feature broke.
2. **The ground-truth cell** - compute the expected answer with pandas,
   over the same files the workers read, and print it. Print `n` too.
3. **The question cell** - ask for your skill in plain English. Name no
   source, no column, no SQL.
4. **The comparison cell** - print expected beside the fleet's answer, and
   print the plausible-but-wrong value a reader might otherwise accept.

Point 4 is the one that matters. Notebook 15 prints what the mean would be
if empty workers were averaged in as zeros, precisely so a reader can tell
a right answer from a believable one. Do the same for your skill: work out
how it would be wrong, and print that number next to the right one.

A notebook that prints only the fleet's answer proves nothing - the answer
always looks reasonable.

### Executing it

```bash
docker exec jupyter sh -c \
  "cd /notebooks && jupyter nbconvert --to notebook --execute --inplace \
   --ExecutePreprocessor.timeout=800 <NN>_<name>.ipynb"
```

It must complete without a retry. If it only passes on a second attempt,
say so in the PR - that usually means the head is retrying something, and
it is worth knowing why before the skill is merged.

## 7. Build, run, and verify — the full loop

This is the whole contribution cycle. Work it end to end yourself; the
only things a human does are fork the repository at the start and open the
pull request at the end.

**Loop budget: 10.** If step 5 has not passed after ten attempts, stop and
write up what you tried and why it failed. That write-up is a useful
contribution; ten more guesses is not.

### Step 1 — bring the stack up

```bash
cd examples/notebooks
cp .env.example .env        # then fill in LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
docker compose --profile agents up -d
```

That is redis, the composer UI, Jupyter, a head and two workers. Without
`--profile agents` you get the infrastructure but no agents, and every
skill call fails with "no online worker reports the X capability".

### Step 2 — write the skill, its tests, and its notebook

Sections 1–6 above. All five artifacts.

### Step 3 — put the notebook where it is actually served

```
docker/jupyter/notebooks/<NN>_<name>.ipynb
```

**Not** `examples/notebooks/` — that directory holds the compose file and
nothing else. The Jupyter service bakes its notebooks in from
`docker/jupyter/notebooks/` at image build time
(`docker/jupyter/Dockerfile`: `COPY docker/jupyter/notebooks/ /notebooks/`).

### Step 4 — rebuild BOTH images, then recreate

This is the step most likely to waste your time. The notebook is baked
into the **notebooks** image, and the skill into the **agents** image, so
changing either one means rebuilding that image. Recreating a service
without rebuilding its image runs exactly what ran before.

Both are tag-selected by the compose, so build to the tag it reads:

```bash
cd <repo root>
docker build --platform linux/amd64 -f harness/Dockerfile \
  -t ghcr.io/disys-lab/scarlet-agents:local .
docker build --platform linux/amd64 -f docker/jupyter/Dockerfile \
  -t ghcr.io/disys-lab/scarlet-notebooks:local .

cd examples/notebooks
AGENTS_VERSION=local NOTEBOOKS_VERSION=local \
  docker compose --profile agents up -d --force-recreate
```

`--platform linux/amd64` for maximum compatibility — build it the same way
wherever you are.

### Step 5 — run your notebook against the live fleet

```bash
docker exec scarlet-notebooks-jupyter sh -c \
  "cd /notebooks && jupyter nbconvert --to notebook --execute --inplace \
   --ExecutePreprocessor.timeout=800 <NN>_<name>.ipynb"
```

Passing means it ran **and** the number matches the ground truth your
notebook computed. A notebook that completes while printing a wrong answer
has not passed — that is the failure mode here, not crashes.

Also run the unit suite, which needs no LLM endpoint:

```bash
python -m pytest harness/tests/ -q
```

### Step 6 — on failure, fix and go round again

Change the skill, then **rebuild the agents image only** and recreate just
the agent services — the notebook has not changed, so its image has not
either:

```bash
docker build --platform linux/amd64 -f harness/Dockerfile \
  -t ghcr.io/disys-lab/scarlet-agents:local .
cd examples/notebooks
AGENTS_VERSION=local docker compose --profile agents up -d \
  --force-recreate agent-head agent-worker1 agent-worker2
```

If you changed the notebook instead, rebuild the notebooks image and
recreate `jupyter`.

### Step 7 — stop

**"Syntactically correct" is not done. "The files are written" is not
done.** Done means step 5 ran and passed: the unit suite green, and your
notebook executed against a live fleet with the number matching your
ground truth.

If you have written the artifacts but not executed them, you are at step 4
and the job is half finished. Every defect this process exists to catch -
a test that cannot even collect, a plan whose two branches are identical,
a statistic that is self-consistent and wrong - is invisible until
something runs.

Successful: you are done. Tell the human to open the PR.
Out of budget: stop and write up what failed.

### Troubleshooting

**A port is already in use.** The stack binds 6380, 8501 and 8888. If
something already holds one, do not edit the compose file — put an
override beside it and pass both:

```bash
docker compose -f docker-compose.yml -f ports.override.yml --profile agents up -d
```

**"no online worker currently reports the X capability."** Either the
agents are not up (did you pass `--profile agents`?) or your skill is not
in the image you are running. Check it registered:

```bash
docker run --rm ghcr.io/disys-lab/scarlet-agents:local python -c \
  "from scarlet_agentic_harness.skills.registry import discover_skills; print(sorted(discover_skills()))"
```

If your skill is not in that list, step 4 did not rebuild what you think
it did.

**The notebook is not in Jupyter.** You put it in `examples/notebooks/`,
or you recreated the jupyter service without rebuilding its image.

### If you have no LLM endpoint

Steps 1 and 2 need nothing but Docker. **Step 3 needs an OpenAI-compatible
endpoint and key**, because the head agent is itself an LLM caller - it is
what turns the question into a skill invocation. Without one there is no
head, so there is no live run.

If you do not have an endpoint, that is fine and expected. Do steps 1 and
2, write the notebook anyway, and submit with step 3 unrun - a maintainer
will run it at merge.

What is not fine is skipping it silently. Put this in the pull request
description, verbatim:

```
Step 3 (live fleet) NOT RUN - no LLM endpoint available.
Steps 1 and 2 pass: <paste the pytest summary line>
Notebook written but not executed.
```

A reviewer who knows the live path is unverified will check it. One who
assumes it passed will not, and the bugs this catches are the ones that
return a plausible number rather than an error.

---

## 8. Checklist

- [ ] Skill in `skills/core/`, unique `name`, imports with no side effects
- [ ] `contribute` returns nothing; `coordinate` returns a status dict
- [ ] Error returns carry `detail` and `retryable`
- [ ] `coordinate` returns bad input as an error dict rather than raising
- [ ] `contribute`'s failure path is deliberate - raise, or flag it in the
      readiness message if the coordinator needs to tell it apart
- [ ] No file path accepted; data reached via `load_local_matrix`
- [ ] `columns` and `conditions` accepted if it aggregates
- [ ] `scarlet_names()` implemented if it uses a Mapper or Federator
- [ ] Seeded generator returning its data
- [ ] Tests compare against computed ground truth, not constants
- [ ] Every error branch tested
- [ ] Mutation-tested: broke the skill, a test failed
- [ ] Notebook runs end to end against a live fleet - or, with no LLM
      endpoint, is written and the PR says step 3 was not run
- [ ] `Limitations` section in the module docstring
- [ ] Full unit suite still passes

If you wrote a **compound** skill, these as well:

- [ ] `test_compound_skill_conformance.py` passes - it found your skill
      on its own, you did not have to add it
- [ ] Every name in every `expression` is bound in that step's `variables`
- [ ] No two steps are identical; every declared parameter is consumed
- [ ] `returns` re-exports the headline number **and** what a caller needs
      to compose with it or sanity-check it (`n`, `df`, `columns`)
- [ ] At least one test lets `combine` and `distribution` run for real and
      compares against a number computed elsewhere (scipy, or by hand)
- [ ] If it reports a p-value: tested with a statistic of **each sign**,
      and the p-value is in [0, 1] both times

---

## 9. Stating limitations

Every skill gets a `Limitations` section. This is not boilerplate - it is
how the next person knows whether to reach for it:

```python
"""
...

Limitations
-----------
- Assumes values are roughly normal; heavy tails make the result
  misleading rather than wrong.
- Needs n > 30 per worker. Below that the result is returned anyway,
  so check `n` before trusting it.
- Not for streaming data: reads a snapshot, so a window overlapping a
  write is not atomic.
"""
```

Say what it is **not** for, and where it is quietly inaccurate rather than
loudly broken. "No known limitations" is never the right answer.

---

## 10. Cleanup

Leave nothing behind:

```bash
docker compose --profile agents down
docker rmi scarlet-agents:local          # if you built it only for this
rm -rf harness/tests/data/*.csv          # generated data, not source
```

Do not commit:

- generated CSVs or Parquet files
- notebook outputs containing your endpoint, keys, or hostnames
- `.env`

Check before you open a pull request:

```bash
git diff --cached | grep -iE 'api[_-]?key|secret|token|password|https?://'
```

---

## What good looks like

The best contribution is small and sharp: one computation, done properly,
with tests that would catch it breaking and a notebook a stranger can
follow. A skill that does three things is three skills.
