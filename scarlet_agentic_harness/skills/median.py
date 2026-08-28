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
import os
import random
import time

from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.skills.base import Skill

_READY_MSG_TYPE = "median_contribution_ready"


def _local_numbers() -> list[float]:
    raw = os.environ.get("LOCAL_NUMBERS", "")
    if not raw.strip():
        return []
    return [float(tok) for tok in raw.split(",") if tok.strip()]


class MedianSkill(Skill):
    name = "median"
    description = (
        "Compute the median of the real numbers held privately across all "
        "currently-registered worker agents. Each worker holds its own "
        "unordered local list; this skill coordinates sorting, exchange, and "
        "merge across workers and returns a single global median value."
    )
    coordinate_timeout = 15.0

    def coordinator_for(self, ctx: HarnessContext, workers: list[str]) -> str:
        return random.choice(workers)

    def contribute(self, ctx: HarnessContext, request: dict) -> None:
        sorted_local = sorted(_local_numbers())

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

        coordinator = request["coordinator"]
        if ctx.agent_id != coordinator:
            # Peer-to-peer readiness signal, on the LOCAL bus - the head is
            # not involved in this exchange at all (two-channel design:
            # local_bus is for intra-device-group peer communication).
            ctx.buses.local_bus.Send(coordinator, {
                "type": _READY_MSG_TYPE,
                "request_id": request["request_id"],
                "from": ctx.agent_id,
                "count": len(sorted_local),
                "map_status": bool(map_status),
                "map_error": str(map_exc) if map_exc else None,
            })
        # If this worker IS the coordinator, no self-message is needed:
        # coordinate() runs synchronously right after this in the same
        # process (see worker.py's skill_coordinate branch) and will read
        # its own just-Mapped value back via AllGather.

    def coordinate(self, ctx: HarnessContext, request: dict, workers: list[str]) -> dict:
        others = [w for w in workers if w != ctx.agent_id]

        ready_from: set[str] = set()
        deadline = time.time() + self.coordinate_timeout
        while len(ready_from) < len(others) and time.time() < deadline:
            msg = ctx.buses.local_bus.Receive(timeout=1)
            if not msg:
                continue
            body = msg.get("body", {})
            if (
                body.get("type") == _READY_MSG_TYPE
                and body.get("request_id") == request["request_id"]
            ):
                if body.get("map_status") is False:
                    return {
                        "status": "error",
                        "detail": f"worker {body.get('from')} failed to Map its "
                                  f"local partition: {body.get('map_error')}",
                    }
                ready_from.add(body["from"])

        missing = set(others) - ready_from
        if missing:
            return {
                "status": "error",
                "detail": f"workers did not report ready in time: {sorted(missing)}",
            }

        mapper = ctx.mapper(request["mapper_name"])
        gathered, status, exc = mapper.AllGather()
        if not status:
            return {"status": "error", "detail": f"AllGather failed: {exc}"}

        partitions = list(gathered.values())
        merged = list(heapq.merge(*partitions))
        n = len(merged)

        mapper.clearAll()

        if n == 0:
            return {"status": "error", "detail": "no data across any worker"}
        if n % 2 == 1:
            median = merged[n // 2]
        else:
            median = (merged[n // 2 - 1] + merged[n // 2]) / 2

        return {
            "status": "ok",
            "result": median,
            "detail": f"n={n} across {len(gathered)} workers",
        }
