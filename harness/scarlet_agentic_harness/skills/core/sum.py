"""
SumSkill — the first Federator-backed skill, and the first to accept a
parameter (`transform`) rather than taking no arguments.

Unlike median, sum *is* an associative reduction - Federator exists for
exactly this. But the coordinator is still a randomly-assigned worker (the
Skill base default, not the head - see base.py), so the shape here mirrors
median's: contributors Map their local contribution and signal readiness on
the local bus; the coordinator waits for everyone, then Aggregates.

The `transform` parameter is what makes this a genuine building block rather
than a single-purpose skill: "identity" gives Sigma(x), "square" gives
Sigma(x^2) - together with n (reported alongside the total on every call),
those are exactly the three numbers a mean/variance/stddev needs. Composing
those from two `sum` calls plus a local (non-distributed) combine step is
the concrete case this was built for - see the variance discussion in
conversation history. No composition/combine code lives here on purpose:
this skill only needs to know how to sum, not what a caller does with two
sums.
"""
import time

import numpy as np
from scarlets.core.Mapper import Mapper

from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.skills.base import Skill
from scarlet_agentic_harness import local_matrix
from scarlet_agentic_harness.skills import predicate

_READY_MSG_TYPE = "sum_contribution_ready"
_TRANSFORMS = {
    "identity": lambda x: x,
    "square": lambda x: x * x,
}


class SumCoreSkill(Skill):
    """
    The first `Federator`-backed `Skill`, and the first to accept a parameter (`transform`).

    Unlike median, sum *is* an associative reduction - `Federator`
    exists for exactly this. But the coordinator is still a
    randomly-assigned worker (the `Skill` base default, not the head),
    so the shape mirrors `MedianSkill`'s: contributors `Map` their local
    contribution and signal readiness on the local bus; the coordinator
    waits for everyone, then `Aggregate`s.

    ``transform`` is what makes this a genuine building block:
    ``"identity"`` gives sum(x), ``"square"`` gives sum(x^2) - together
    with `n` (reported alongside the total on every call), those are
    exactly the three numbers a mean/variance/stddev needs, composable
    from two `sum` calls plus a local `combine` step. No composition
    code lives here on purpose - this skill only needs to know how to
    sum, not what a caller does with two sums.
    """

    name = "sum_core"
    description = (
        "Compute the sum of the real numbers held privately across all "
        "currently-registered worker agents, optionally applying a transform "
        "to each value first. Also returns n, the number of contributing "
        "workers. Composable: Sigma(x) via transform=identity and Sigma(x^2) "
        "via transform=square, together with n, are enough to derive mean, "
        "variance, and standard deviation without a dedicated skill for each."
    )
    parameters = {
        "type": "object",
        "properties": {
            "transform": {
                "type": "string",
                "enum": ["identity", "square"],
                "description": "Applied to each value before summing. identity for a plain sum, square for a sum of squares.",
            },
            "objective": {
                "type": "string",
                "description": (
                    "A plain-language statement of what measurements are wanted, e.g. "
                    "\"vibration and torque readings\". Do NOT name a data source, a "
                    "file or a column - each worker knows its own data and selects and "
                    "queries it locally. Describe the goal, not the location."
                ),
            },
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "The exact column list every worker should read, as returned by "
                    "the agree_representation skill. Pass this whenever workers may "
                    "hold different columns - without it each worker reads whatever "
                    "it has and the shapes will not aggregate."
                ),
            },
            "workers": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Agent ids that should contribute. Omit for all of them. Use this to "
                    "aggregate over only the workers that hold a named column, as reported "
                    "by list_sources - a worker lacking the column would otherwise fail the "
                    "whole call."
                ),
            },
            "conditions": predicate.CONDITIONS_SCHEMA,
        },
        "required": [],
    }
    coordinate_timeout = 15.0

    def scarlet_names(self, mapper_name: str) -> list[str]:
        """
        Backed by a `Federator`. Returns the two names its `__init__` actually constructs.

        Must match what `Federator.__init__` constructs - see
        `Skill.scarlet_names`'s docstring for why this can't just be
        imported instead.
        """
        # Must match what Federator.__init__ actually constructs (scarlets'
        # formulations/Federator.py) - see Skill.scarlet_names()'s docstring
        # for why this can't just be imported instead.
        return [f"{mapper_name}_mapper_reducer", f"{mapper_name}_mapper_global"]

    def contribute(self, ctx: HarnessContext, request: dict) -> None:
        """Sum this worker's local numbers (after `transform`), `Map` `[total, count]`, and signal readiness."""
        # Self-filter, the same shape query_feature uses: a worker the caller
        # did not ask for sends nothing at all, not even a "not applicable"
        # signal. coordinate() narrows its expected set identically below -
        # narrowing only one of the two turns a filter into a readiness
        # timeout, which reads as a hang rather than as a filter.
        requested = request.get("params", {}).get("workers")
        if requested and ctx.agent_id not in requested:
            return

        params = request.get("params", {})
        transform_name = params.get("transform", "identity")
        transform = _TRANSFORMS.get(transform_name, _TRANSFORMS["identity"])

        # The head states an objective; this worker decides for itself which
        # of its own sources answers it and writes its own SQL. Nothing here
        # is told a path, a filename or a column - see local_matrix.
        matrix, meta = local_matrix.load_local_matrix(
            ctx,
            params.get("objective", "all available numeric measurements"),
            columns=params.get("columns"),
            conditions=params.get("conditions"),
        )
        matrix = transform(matrix)  # elementwise: identity or square

        # Co-aggregate [sum, count] as one numpy array in a single Federator
        # round trip, rather than reporting n = len(workers). Those are two
        # different numbers: len(workers) is how many partial sums got
        # combined, not how many underlying elements they represent (a
        # worker holding 4 numbers contributes exactly 1 partial sum). Mean/
        # variance composition needs total element count, so that's what n
        # has to mean here. operator.add (Federator's SUM op) is elementwise
        # on numpy arrays, so both values fold correctly in one Aggregate().
        # Contribution is (2, ncols): row 0 is this worker's column sums,
        # row 1 is the element count behind each of those sums.
        #
        # Two rows rather than one because mean/variance composition needs
        # the element count, and len(workers) is the wrong number - a worker
        # holding 80 rows contributes exactly one partial sum. Carrying the
        # count alongside keeps both folding in a single Aggregate(), since
        # Federator's SUM op is elementwise on numpy arrays.
        #
        # Per-column counts rather than one scalar: rows are dropped per
        # row, not per column, but keeping the count aligned to the sum it
        # belongs to means a later change to column-wise dropping needs no
        # change here. It also makes the contribution rectangular, which is
        # what Federator requires.
        #
        # This shape is identical across workers as long as they agree on
        # the column count - which is exactly what the consensus step
        # negotiates. Row counts may differ freely (80/100/120/90 here) and
        # never reach the Federator, because summing has already reduced
        # that axis away.
        column_sums = matrix.sum(axis=0)
        column_counts = np.full(matrix.shape[1], matrix.shape[0], dtype=float)
        contribution = np.vstack([column_sums, column_counts])

        federator = ctx.federator(request["mapper_name"], op=Mapper.SUM)
        _, map_status, map_exc = federator.Map(contribution, key=ctx.agent_id)

        # Always signal, even to self if this worker is also the coordinator
        # - see median.py's contribute() for why (a coordinator-side Map()
        # failure has nowhere else to be reported).
        ctx.buses.local_bus.Send(request["coordinator"], {
            "type": _READY_MSG_TYPE,
            "request_id": request["request_id"],
            "from": ctx.agent_id,
            # The coordinator needs this to size the Aggregate identity
            # element; only a contributor knows how wide its matrix is.
            "ncols": int(matrix.shape[1]),
            # How many rows this worker actually contributed. Zero is a real
            # answer once filtering exists - "I have nothing in that window"
            # - and it is arithmetically harmless, because a zero sum over a
            # zero count moves neither the numerator nor the denominator.
            #
            # But it is invisible in the total, and the head will otherwise
            # infer from a successful round that every worker had data.
            # Observed exactly that: a window only one worker could answer
            # returned the right mean, and the head reported "no workers were
            # missing readings for this filter", which was false for three of
            # the four. The number has to arrive with the fact.
            "rows": int(matrix.shape[0]),
            "map_status": bool(map_status),
            "map_error": str(map_exc) if map_exc else None,
        })

    def coordinate(self, ctx: HarnessContext, request: dict, workers: list[str]) -> dict:
        """Run `_coordinate`, then release the router queue for this `request_id` regardless of outcome."""
        try:
            return self._coordinate(ctx, request, workers)
        finally:
            # Router queues are keyed by request_id (a UUID, never reused) -
            # without this, every sum invocation over the process's
            # lifetime leaks one queue. See router.py.
            ctx.buses.local_router.forget(request["request_id"])

    def _coordinate(self, ctx: HarnessContext, request: dict, workers: list[str]) -> dict:
        """
        Wait for every worker's readiness signal, then `Aggregate` their partial sums.

        Returns
        -------
        dict
            ``{"status": "ok", "result": <sum>, "n": <element count>, "detail": ...}``
            on success; ``{"status": "error", "detail": ..., "retryable": ...}``
            on a Map failure, missing workers, cancellation, or an
            Aggregate failure.
        """
        # Narrowed in step with contribute()'s self-filter. The coordinator
        # itself may legitimately be absent from this list: it still
        # coordinates, it just contributes nothing.
        requested = request.get("params", {}).get("workers")
        if requested:
            absent = [w for w in requested if w not in workers]
            if absent:
                # Quietly aggregating fewer workers than asked for would hand
                # back a plausible number for a different question.
                return {
                    "status": "error",
                    "detail": (f"requested workers not available: {sorted(absent)} "
                               f"(dispatched: {sorted(workers)})"),
                    "retryable": False,
                }
            workers = [w for w in workers if w in requested]
            if not workers:
                return {
                    "status": "error",
                    "detail": "requested worker list matches none of the dispatched workers",
                    "retryable": False,
                }

        ready_from: set[str] = set()
        rows_from: dict[str, int] = {}
        ncols: set[int] = set()
        # Reported before anything has checked in, not just after the
        # first one - a check-in arriving in that early window should
        # still see "0 of N so far", not nothing at all.
        ctx.report_progress(ready_count=0, expected_count=len(workers))
        # Staggered rather than flat: the wait extends while workers are
        # still reporting in, up to a hard ceiling. A filtered query adds
        # work to every worker's path, and a flat timeout has to be either
        # generous enough for the slowest or short enough to catch a hang.
        still_waiting = self.staggered_deadline(len(workers))
        while len(ready_from) < len(workers) and still_waiting(len(ready_from)):
            if ctx.cancelled.is_set():
                # head.run_skill() already started a fresh attempt under a
                # new request_id (see cancellation.py) - no point finishing
                # this one, nothing is waiting on its answer anymore.
                return {"status": "error", "detail": "cancelled", "retryable": False}
            msg = ctx.buses.local_router.receive_for(request["request_id"], timeout=1)
            if not msg:
                continue
            body = msg.get("body", {})
            if body.get("type") == _READY_MSG_TYPE:
                if body.get("map_status") is False:
                    return {
                        "status": "error",
                        "detail": f"worker {body.get('from')} failed to Map its "
                                  f"local sum: {body.get('map_error')}",
                        "retryable": True,
                    }
                ready_from.add(body["from"])
                if body.get("rows") is not None:
                    rows_from[body["from"]] = int(body["rows"])
                if body.get("ncols") is not None:
                    ncols.add(int(body["ncols"]))
                ctx.report_progress(ready_count=len(ready_from), expected_count=len(workers))

        if ctx.cancelled.is_set():
            return {"status": "error", "detail": "cancelled", "retryable": False}

        missing = set(workers) - ready_from
        if missing:
            return {
                "status": "error",
                "detail": f"workers did not report ready in time: {sorted(missing)}",
                "retryable": True,
            }

        federator = ctx.federator(request["mapper_name"], op=Mapper.SUM)

        # The identity element has to match the contribution's shape, which
        # is now (2, ncols) rather than the old flat [sum, count]. Seeding
        # with the wrong shape fails loudly inside numpy ("operands could not
        # be broadcast together with shapes (2,5) (2,)") rather than
        # silently truncating, but it still has to be right, and only the
        # contributors know ncols - so it is read back from the readiness
        # signals rather than assumed.
        #
        # Zeros, not a real value: Federator.Aggregate(x) folds the
        # AllGather results onto whatever x it is given, and the
        # coordinator's own contribution is already among those results
        # (it Mapped in contribute()). Seeding with anything but the
        # identity element double-counts it.
        if not ncols:
            return {
                "status": "error",
                "detail": "no worker reported a column count - nothing to aggregate",
                "retryable": True,
            }
        if len(ncols) != 1:
            return {
                "status": "error",
                "detail": (f"workers disagree on column count {sorted(ncols)} - "
                           f"reshape consensus required before aggregation"),
                "retryable": False,
            }
        width = next(iter(ncols))

        totals, status, exc = federator.Aggregate(np.zeros((2, width), dtype=float))
        if not status:
            return {"status": "error", "detail": f"Aggregate failed: {exc}", "retryable": True}

        totals = np.atleast_2d(np.asarray(totals, dtype=float))
        column_sums = totals[0]
        # Per-column counts are identical by construction (rows are dropped
        # whole, never per column), so one representative count is the
        # element count behind every column. Taking the max rather than [0]
        # keeps this honest if that ever stops being true: a caller
        # composing a mean would otherwise divide by a count that silently
        # under-reports.
        element_count = int(totals[1].max()) if totals.shape[0] > 1 else 0
        transform_name = request.get("params", {}).get("transform", "identity")
        empty_workers = sorted(w for w, r in rows_from.items() if r == 0)
        return {
            "status": "ok",
            "result": column_sums.tolist(),
            "n": element_count,
            "columns": int(width),
            # Named, not just counted: "worker2 and worker4 had nothing in
            # range" is the answer to a question the total cannot express.
            "empty_workers": empty_workers,
            "rows_per_worker": dict(sorted(rows_from.items())),
            # The empty workers are named in the detail, not just in a field,
            # because the head narrates from this string. Left out, it fills
            # the gap by inference and gets it wrong - it reported that no
            # worker was missing readings when three of four had none.
            "detail": (f"sum(transform={transform_name}) per column over n={element_count} "
                       f"rows x {width} columns across {len(workers)} workers"
                       + (f"; {len(empty_workers)} of them matched no rows in "
                          f"range and contributed nothing: "
                          f"{', '.join(empty_workers)}" if empty_workers else "")),
        }
