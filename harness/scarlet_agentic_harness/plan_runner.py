"""Executes a compound skill's plan, one step at a time, over a shared namespace."""


class StepResult:
    """
    Handles one plan step's result: bind its outputs, or abort the plan.

    Exists per step because `run_skill` answers through a callback rather
    than a return value - the work happens on other processes - so the
    "what happens next" has to carry which step it belongs to.

    Parameters
    ----------
    runner : PlanRunner
    step : Step
        The step whose result this is.
    index : int
        Its position in the plan.
    """

    def __init__(self, runner, step, index: int):
        self._runner = runner
        self._step = step
        self._index = index

    def __call__(self, result: dict) -> None:
        """Bind outputs and advance, or abort carrying the child's retryable."""
        # RULE 3 - abort. Carry the child's retryable upward so an
        # unretryable failure is not retried by whoever called us.
        if result.get("status") != "ok":
            self._runner.fail(
                f"step {self._step.skill!r} failed: {result.get('detail')}",
                result.get("retryable", False))
            return
        for var, field in self._step.produces.items():
            self._runner.bind(var, result.get(field))
        self._runner.advance(self._index + 1)


class PlanRunner:
    """
    Runs a `CompoundSkill`'s plan over one shared namespace.

    The namespace starts as the compound's own params and accumulates each
    step's declared outputs, so a later step can read what an earlier one
    produced. Three rules govern stepping, and each is a separate branch in
    `advance` so removing one is visible:

    RULE 1 - a step with no outputs always runs; it is a check.
    RULE 2 - a step whose outputs are all already bound is skipped.
    RULE 3 - a step that fails aborts the plan (see `StepResult`).

    Parameters
    ----------
    compound : CompoundSkill
    params : dict
        Seeds the namespace. Spread into every step, which is how a filter
        passed to the compound reaches each one.
    config, buses : see `run_skill`
    on_result : callable
        Called once with the plan's result.
    skills : dict
        Name -> instance, for resolving each step.
    on_event : callable or None
    depth : int
        Nesting depth, carried down so `run_skill` can cap recursion.
    run_skill_kwargs : dict
        Forwarded unchanged to every step.
    """

    def __init__(self, compound, params: dict, config, buses, on_result,
                 skills: dict, on_event, depth: int, run_skill_kwargs: dict):
        self._compound = compound
        self._ns = dict(params)
        self._steps = list(compound.plan)
        self._config = config
        self._buses = buses
        self._on_result = on_result
        self._skills = skills
        self._on_event = on_event
        self._emit = on_event or (lambda _event: None)
        self._depth = depth
        self._run_skill_kwargs = run_skill_kwargs

    def run(self) -> None:
        """Start at the first step."""
        self.advance(0)

    def bind(self, var: str, value) -> None:
        """Record one step output in the shared namespace."""
        self._ns[var] = value

    def fail(self, detail: str, retryable: bool) -> None:
        """End the plan with an error."""
        self._on_result({"status": "error", "detail": detail,
                         "retryable": retryable})

    def _finish(self) -> None:
        """Return whatever the compound declared it returns."""
        detail = f"{self._compound.name}: {len(self._steps)} step(s)"
        if isinstance(self._compound.returns, str):
            self._on_result({"status": "ok",
                             "result": self._ns.get(self._compound.returns),
                             "detail": detail})
            return
        out = {"status": "ok", "detail": detail}
        out.update({field: self._ns.get(var)
                    for field, var in self._compound.returns.items()})
        self._on_result(out)

    def advance(self, i: int) -> None:
        """
        Dispatch step `i`, skipping any already satisfied.

        Parameters
        ----------
        i : int
            Index to start from. Past the end means the plan is done.
        """
        # Skip forward over anything already satisfied before dispatching.
        while i < len(self._steps):
            step = self._steps[i]
            # RULE 1 - always-run. A step with no outputs is a check.
            if not step.produces:
                break
            # RULE 2 - skip. Every output is already bound.
            if all(self._ns.get(var) is not None for var in step.produces):
                i += 1
                continue
            break

        if i >= len(self._steps):
            self._finish()
            return

        step = self._steps[i]
        self._emit({"event": "step", "skill": step.skill,
                    "of": self._compound.name, "index": i})

        if step.skill not in self._skills:
            self.fail(f"{self._compound.name!r} plan references unknown skill "
                      f"{step.skill!r}", False)
            return

        # Imported here, not at module scope: dispatch imports this module,
        # so a top-level import would be circular - and going through the
        # module keeps run_skill patchable where callers already patch it.
        from scarlet_agentic_harness import dispatch as dispatch_mod

        # Ambient namespace first, then this step's own params overlaid with
        # every "$name" resolved from it.
        step_params = {**self._ns,
                       **dispatch_mod.resolve_refs(step.params, self._ns)}
        dispatch_mod.run_skill(
            self._skills[step.skill], step_params, self._config, self._buses,
            StepResult(self, step, i), skills=self._skills,
            on_event=self._on_event, depth=self._depth + 1,
            **self._run_skill_kwargs)
