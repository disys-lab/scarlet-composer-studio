"""
MedianSkill — the reference Skill implementation.

Median is not an associative reduction (you cannot combine two workers'
local medians into the global median the way you can combine two local
sums), so it can't be built on Federator the way sum/mean will be. Instead:
every worker sorts its local partition and Maps it under its own agent id;
a randomly-assigned coordinator (per DESIGN_v3.md section 8.5: "workers do
not self-assign tasks", so the head assigns it) waits for the other workers
to signal readiness on the local bus, then AllGathers every partition and
does a real k-way merge.

Where each worker's numbers come from: a LOCAL_NUMBERS env var
(comma-separated floats) for now. This is a deliberate placeholder for
scarlet-composer-studio's own three-tier data source system
(DESIGN_v3.md section 9) - not a permanent design choice.
"""
import heapq

import numpy as np
import time

from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.skills.base import Skill
from scarlet_agentic_harness import local_matrix
from scarlet_agentic_harness.skills import predicate

_READY_MSG_TYPE = "median_contribution_ready"


class MedianSkill(Skill):
    """
    Reference `Skill`: the median of numbers held privately across workers.

    Median is not an associative reduction (you cannot combine two
    workers' local medians into the global median the way you can
    combine two local sums), so it can't be built on `Federator` the way
    `SumSkill` is. Instead: every worker sorts its local partition and
    `Map`s it under its own agent id; the randomly-assigned coordinator
    waits for the other workers to signal readiness on the local bus,
    then `AllGather`s every partition and does a real k-way merge.

    Where each worker's data comes from: `local_matrix.load_local_matrix`
    - the worker picks one of its own configured sources, writes its own
    SQL against it, and returns a 2-D matrix. It is never told a path, a
    filename or a column. This replaced the `CSV_PATH`/`local_numbers`
    placeholder, which could only ever read one file and one column named
    `value`.

    The median is per-column: the result is a list with one median per
    numeric column, not a single scalar.
    """

    name = "median"
    description = (
        "Compute the median of the real numbers held privately across all "
        "currently-registered worker agents. Each worker holds its own "
        "unordered local list; this skill coordinates sorting, exchange, and "
        "merge across workers and returns a single global median value."
    )
    parameters = {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": (
                    "A plain-language statement of what measurements are wanted. Do NOT "
                    "name a data source, a file or a column - each worker knows its own "
                    "data and selects and queries it locally."
                ),
            },
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "The exact column list every worker should read, as returned by the "
                    "agree_representation skill. Pass this whenever workers may hold "
                    "different columns."
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

    # No coordinator_for() override needed - Skill's base default (a
    # randomly-chosen worker) is exactly right for median too, and is now
    # the default for every skill, not a median-specific choice.

    def scarlet_names(self, mapper_name: str) -> list[str]:
        """Backed by a single `Mapper`. Returns `[mapper_name]`."""
        return [mapper_name]

    def contribute(self, ctx: HarnessContext, request: dict) -> None:
        """Sort this worker's local numbers, `Map` them, and signal readiness to the coordinator."""
        # Self-filter, the same shape query_feature uses: a worker the caller
        # did not ask for sends nothing at all, not even a "not applicable"
        # signal. coordinate() narrows its expected set identically below -
        # narrowing only one of the two turns a filter into a readiness
        # timeout, which reads as a hang rather than as a filter.
        requested = request.get("params", {}).get("workers")
        if requested and ctx.agent_id not in requested:
            return

        # Each column is sorted independently. The median is per-column now,
        # so a row is not a meaningful unit here - sorting whole rows by
        # their first element (what a naive sort of a 2-D array does) would
        # silently produce the wrong answer for every column but the first.
        _p = request.get("params", {})
        matrix, meta = local_matrix.load_local_matrix(
            ctx,
            _p.get("objective", "all available numeric measurements"),
            columns=_p.get("columns"),
            conditions=_p.get("conditions"),
        )
        sorted_local = np.sort(matrix, axis=0)

        mapper = ctx.mapper(
            request["mapper_name"],
            description=(
                f"Sorted local partitions for median request "
                f"{request['request_id']}. Each worker Maps its sorted local "
                f"list under its own agent id as key; the coordinator "
                f"AllGathers and merges them. Each partition is a 2-D "
                f"(rows, columns) array sorted down each column."
            ),
        )
        _, map_status, map_exc = mapper.Map(sorted_local, key=ctx.agent_id)

        # Always signal readiness, even to self if this worker is also the
        # coordinator - if we skip self-signaling, a Map() failure on the
        # coordinator's own contribution has nowhere to be reported: nothing
        # else checks it, and coordinate() would silently AllGather one
        # fewer partition than expected instead of erroring. Sending to your
        # own agentId over Messenger works the same as sending to anyone
        # else's - it's just another agent's inbox.
        ctx.buses.local_bus.Send(request["coordinator"], {
            "type": _READY_MSG_TYPE,
            "request_id": request["request_id"],
            "from": ctx.agent_id,
            "count": int(sorted_local.shape[0]),
            "map_status": bool(map_status),
            "map_error": str(map_exc) if map_exc else None,
        })

    def coordinate(self, ctx: HarnessContext, request: dict, workers: list[str]) -> dict:
        """Run `_coordinate`, then release the router queue for this `request_id` regardless of outcome."""
        try:
            return self._coordinate(ctx, request, workers)
        finally:
            # Router queues are keyed by request_id (a UUID, never reused) -
            # without this, every median invocation over the process's
            # lifetime leaks one queue. See router.py.
            ctx.buses.local_router.forget(request["request_id"])

    def _coordinate(self, ctx: HarnessContext, request: dict, workers: list[str]) -> dict:
        """
        Wait for every worker's readiness signal, then `AllGather` and k-way-merge their sorted partitions.

        Returns
        -------
        dict
            ``{"status": "ok", "result": <median>, "detail": ...}`` on
            success; ``{"status": "error", "detail": ..., "retryable": ...}``
            on a Map failure, missing workers, cancellation, or an
            AllGather failure.
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
                # dispatch.run_skill() already started a fresh attempt under a
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
                                  f"local partition: {body.get('map_error')}",
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

        mapper = ctx.mapper(request["mapper_name"])
        gathered, status, exc = mapper.AllGather()
        if not status:
            return {"status": "error", "detail": f"AllGather failed: {exc}", "retryable": True}

        partitions = [np.atleast_2d(np.asarray(p, dtype=float)) for p in gathered.values()]
        mapper.clearAll()

        if not partitions:
            return {"status": "error", "detail": "no data across any worker", "retryable": True}

        # Column counts must agree or the stack is meaningless - a worker
        # offering a different number of columns is a consensus failure, not
        # something to paper over by truncating to the narrowest. Report it
        # as what it is so the coordinator's hint can address it.
        widths = {p.shape[1] for p in partitions}
        if len(widths) != 1:
            return {
                "status": "error",
                "detail": (f"workers disagree on column count {sorted(widths)} - "
                           f"reshape consensus required before median"),
                "retryable": False,
            }

        # Row counts may differ freely (that is the point of the sprint's
        # data), so partitions stack along rows. heapq.merge is gone: it
        # merges 1-D sorted sequences, and there is no k-way merge that is
        # simultaneously correct for every column of a 2-D stack. The
        # per-column sort above is preserved within each partition; numpy
        # re-sorts the stacked column, which is O(n log n) on data this size.
        stacked = np.vstack(partitions)
        n = int(stacked.shape[0])
        if n == 0:
            return {"status": "error", "detail": "no data across any worker", "retryable": True}

        medians = np.median(stacked, axis=0)

        return {
            "status": "ok",
            "result": medians.tolist(),
            "detail": f"n={n} rows x {stacked.shape[1]} columns across {len(gathered)} workers",
        }
