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
        "LOW-LEVEL BUILDING BLOCK. Prefer a dedicated skill if one exists for "
        "what you are computing - mean, variance, rms, z_test, t_test and "
        "f_test all call this internally and handle the column agreement and "
        "the arithmetic for you. Reach for sum_core directly only when no "
        "dedicated skill fits. "
        "Sums the real numbers held privately across all currently-registered "
        "worker agents, optionally applying a transform first. Returns the "
        "per-column sums and n, the element count behind them. Sigma(x) via "
        "transform=identity, Sigma(x^2) via transform=square."
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
        # Reading the data is guarded the same way the Map below is, and for
        # the same reason: letting it raise reports the round as permanently
        # failed. That is right for a bad column, and wrong for a dropped
        # database connection - a CSV read rarely fails transiently, but a
        # Postgres/Influx/PI one does, and the head would give up on a round
        # a second attempt would have completed.
        #
        # ValueError is ours - a missing source, an unknown filter column, no
        # rows convertible - and will fail identically next time. Anything
        # else came from the connector and is worth one retry.
        try:
            matrix, meta = local_matrix.load_local_matrix(
                ctx,
                params.get("objective", "all available numeric measurements"),
                columns=params.get("columns"),
                conditions=params.get("conditions"),
            )
        except Exception as exc:
            ctx.buses.local_bus.Send(request["coordinator"], {
                "type": _READY_MSG_TYPE,
                "request_id": request["request_id"],
                "from": ctx.agent_id,
                "ncols": 0,
                "rows": 0,
                "read_status": False,
                "read_error": f"{type(exc).__name__}: {exc}",
                "read_retryable": not isinstance(exc, ValueError),
                "map_status": False,
                "map_error": None,
            })
            return

        matrix = transform(matrix)  # elementwise: identity or square

        # Contribution is (2, ncols): row 0 the column sums, row 1 the
        # element count behind each. Both fold in one Aggregate() because
        # Federator's SUM op is elementwise on numpy arrays.
        #
        # The count is carried rather than derived: n must be the number of
        # elements, not len(workers), since a worker holding 80 rows still
        # contributes exactly one partial sum - and mean/variance need the
        # element count.
        #
        # Per-column counts rather than one scalar keep the contribution
        # rectangular, which Federator requires, and keep each count beside
        # the sum it belongs to.
        #
        # Workers must agree on ncols - that is what consensus negotiates.
        # Row counts may differ freely and never reach the Federator, since
        # summing has already reduced that axis away.
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
            # Rows this worker actually contributed. Zero is a real answer
            # once filtering exists, and arithmetically harmless - a zero sum
            # over a zero count moves neither numerator nor denominator.
            #
            # It is also invisible in the total, so the head infers from a
            # successful round that every worker had data. Observed: a window
            # only one worker could answer gave the right mean, and the head
            # reported no workers were missing readings - false for three of
            # four. The count has to travel with the number.
            "rows": int(matrix.shape[0]),
            "read_status": True,
            "read_error": None,
            "read_retryable": False,
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
        deadline = self.staggered_deadline(len(workers))
        while len(ready_from) < len(workers) and deadline.still_waiting(len(ready_from)):
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
                if body.get("read_status") is False:
                    # The worker could not read its data. Retryable only if
                    # the connector raised, not if the request was wrong.
                    return {
                        "status": "error",
                        "detail": (f"worker {body.get('from')} could not read "
                                   f"its data: {body.get('read_error')}"),
                        "retryable": bool(body.get("read_retryable", False)),
                    }
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

        # The identity must match the contribution's (2, ncols) shape. Only
        # contributors know ncols, so it is read back from the readiness
        # signals rather than assumed. A wrong shape raises in numpy rather
        # than truncating silently, but it still has to be right.
        #
        # Zeros specifically: Aggregate(x) folds the AllGather results onto
        # x, and the coordinator's own contribution is already among them -
        # seeding with anything but the identity double-counts it.
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
