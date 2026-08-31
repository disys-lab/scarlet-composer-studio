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
from scarlet_agentic_harness.skills.local_data import local_numbers

_READY_MSG_TYPE = "sum_contribution_ready"
_TRANSFORMS = {
    "identity": lambda x: x,
    "square": lambda x: x * x,
}


class SumSkill(Skill):
    name = "sum"
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
        },
        "required": [],
    }
    coordinate_timeout = 15.0

    def contribute(self, ctx: HarnessContext, request: dict) -> None:
        transform_name = request.get("params", {}).get("transform", "identity")
        transform = _TRANSFORMS.get(transform_name, _TRANSFORMS["identity"])
        values = local_numbers()
        local_total = sum(transform(x) for x in values)

        # Co-aggregate [sum, count] as one numpy array in a single Federator
        # round trip, rather than reporting n = len(workers). Those are two
        # different numbers: len(workers) is how many partial sums got
        # combined, not how many underlying elements they represent (a
        # worker holding 4 numbers contributes exactly 1 partial sum). Mean/
        # variance composition needs total element count, so that's what n
        # has to mean here. operator.add (Federator's SUM op) is elementwise
        # on numpy arrays, so both values fold correctly in one Aggregate().
        federator = ctx.federator(request["mapper_name"], op=Mapper.SUM)
        _, map_status, map_exc = federator.Map(
            np.array([local_total, len(values)], dtype=float), key=ctx.agent_id
        )

        # Always signal, even to self if this worker is also the coordinator
        # - see median.py's contribute() for why (a coordinator-side Map()
        # failure has nowhere else to be reported).
        ctx.buses.local_bus.Send(request["coordinator"], {
            "type": _READY_MSG_TYPE,
            "request_id": request["request_id"],
            "from": ctx.agent_id,
            "map_status": bool(map_status),
            "map_error": str(map_exc) if map_exc else None,
        })

    def coordinate(self, ctx: HarnessContext, request: dict, workers: list[str]) -> dict:
        try:
            return self._coordinate(ctx, request, workers)
        finally:
            # Router queues are keyed by request_id (a UUID, never reused) -
            # without this, every sum invocation over the process's
            # lifetime leaks one queue. See router.py.
            ctx.buses.local_router.forget(request["request_id"])

    def _coordinate(self, ctx: HarnessContext, request: dict, workers: list[str]) -> dict:
        ready_from: set[str] = set()
        # Reported before anything has checked in, not just after the
        # first one - a check-in arriving in that early window should
        # still see "0 of N so far", not nothing at all.
        ctx.report_progress(ready_count=0, expected_count=len(workers))
        deadline = time.time() + self.coordinate_timeout
        while len(ready_from) < len(workers) and time.time() < deadline:
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
        # [0, 0] is SUM's identity element (elementwise) - Federator.Aggregate(x)
        # folds AllGather results onto whatever x you pass, so passing a real
        # value here (rather than the identity element) would double-count
        # the coordinator's own contribution, since it's already in the
        # AllGather results too (it Mapped its own value in contribute()).
        totals, status, exc = federator.Aggregate(np.array([0.0, 0.0]))
        if not status:
            return {"status": "error", "detail": f"Aggregate failed: {exc}", "retryable": True}

        total, element_count = float(totals[0]), int(totals[1])
        transform_name = request.get("params", {}).get("transform", "identity")
        return {
            "status": "ok",
            "result": total,
            "n": element_count,
            "detail": f"sum(transform={transform_name}) over n={element_count} elements across {len(workers)} workers",
        }
