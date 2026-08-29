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
import time

from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.skills.base import Skill
from scarlet_agentic_harness.skills.local_data import local_numbers

_READY_MSG_TYPE = "median_contribution_ready"


class MedianSkill(Skill):
    name = "median"
    description = (
        "Compute the median of the real numbers held privately across all "
        "currently-registered worker agents. Each worker holds its own "
        "unordered local list; this skill coordinates sorting, exchange, and "
        "merge across workers and returns a single global median value."
    )
    coordinate_timeout = 15.0

    # No coordinator_for() override needed - Skill's base default (a
    # randomly-chosen worker) is exactly right for median too, and is now
    # the default for every skill, not a median-specific choice.

    def contribute(self, ctx: HarnessContext, request: dict) -> None:
        sorted_local = sorted(local_numbers())

        mapper = ctx.mapper(
            request["mapper_name"],
            description=(
                f"Sorted local partitions for median request "
                f"{request['request_id']}. Each worker Maps its sorted local "
                f"list under its own agent id as key; the coordinator "
                f"AllGathers and merges them."
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
            "count": len(sorted_local),
            "map_status": bool(map_status),
            "map_error": str(map_exc) if map_exc else None,
        })

    def coordinate(self, ctx: HarnessContext, request: dict, workers: list[str]) -> dict:
        try:
            return self._coordinate(ctx, request, workers)
        finally:
            # Router queues are keyed by request_id (a UUID, never reused) -
            # without this, every median invocation over the process's
            # lifetime leaks one queue. See router.py.
            ctx.buses.local_router.forget(request["request_id"])

    def _coordinate(self, ctx: HarnessContext, request: dict, workers: list[str]) -> dict:
        ready_from: set[str] = set()
        deadline = time.time() + self.coordinate_timeout
        while len(ready_from) < len(workers) and time.time() < deadline:
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

        partitions = list(gathered.values())
        merged = list(heapq.merge(*partitions))
        n = len(merged)

        mapper.clearAll()

        if n == 0:
            return {"status": "error", "detail": "no data across any worker", "retryable": True}
        if n % 2 == 1:
            median = merged[n // 2]
        else:
            median = (merged[n // 2 - 1] + merged[n // 2]) / 2

        return {
            "status": "ok",
            "result": median,
            "detail": f"n={n} across {len(gathered)} workers",
        }
