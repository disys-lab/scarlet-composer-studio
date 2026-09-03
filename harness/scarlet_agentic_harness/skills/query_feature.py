"""
QueryFeatureSkill — one skill, not one per connector type, for reading a
data source a worker knows about locally (see local_config.py). Answers
"does *this* worker have the source named `source_name`", not an open
tag search across the fleet - that's a separate, semantic problem (an
"RollSpeed" on one worker vs. "roll_speed" on another) solved by
AgentDialogue instead (see dialogue.py's context_fn, wired to
local_config.describe_sources()), not by this skill. A caller that
already knows which name it wants - because it configured it itself, or
because a peer's dialogue reply just told it - invokes this skill with
that name.

Shaped like combine.py (no Mapper/Federator, no readiness handshake) but
with sum/median's contribute/coordinate split, *inverted*: contribute()
only runs real work on the one worker (if any) whose local config
actually has `source_name` - every other dispatched worker self-filters
and sends nothing at all, rather than a "not applicable" signal.
coordinate() therefore can't wait for "everyone" the way sum/median do
(most workers will never answer) - it waits for the *first* real
response and returns it immediately; silence until timeout means no
worker in the dispatched group holds that source, a real "not found",
not a transient failure.

No head.py/dispatch changes needed for this - broadcasting to every
worker whose capabilities include "query_feature" and letting each
self-filter inside contribute() is the same shape sum/median already
use; adding a skill isn't supposed to require touching dispatch (see
skills/base.py's own module docstring).
"""
import time

from scarlet_agentic_harness import local_config
from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.skills.base import Skill

_RESULT_MSG_TYPE = "query_feature_result"


class QueryFeatureSkill(Skill):
    """
    One skill, not one per connector type, for reading a data source a worker knows about locally.

    Answers "does *this* worker have the source named `source_name`",
    not an open tag search across the fleet - that's a separate,
    semantic problem solved by `AgentDialogue` instead. A caller that
    already knows which name it wants invokes this skill with that name.

    Shaped like `skills.combine.CombineSkill` (no Mapper/Federator, no
    readiness handshake) but with `SumSkill`/`MedianSkill`'s
    contribute/coordinate split *inverted*: `contribute` only runs real
    work on the one worker (if any) whose local config actually has
    `source_name` - every other dispatched worker self-filters and
    sends nothing at all. `coordinate` therefore waits for the *first*
    real response and returns it immediately; silence until timeout
    means no worker in the dispatched group holds that source, a real
    "not found", not a transient failure.
    """

    name = "query_feature"
    description = (
        "Query a data source this agent already knows the name of - either "
        "one it holds locally (its own ~/.scarlet/config.yaml) or one "
        "relayed through a centralized broker. Use this once you already "
        "know the exact source_name to ask for (from your own config, or "
        "from a peer's answer to a natural-language question about who has "
        "a given feature/tag)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "source_name": {
                "type": "string",
                "description": "Must match a `name` in the answering worker's own local config.",
            },
            "query_payload": {
                "type": "object",
                "description": (
                    "Connector-specific query, passed straight through to the "
                    "matching connector's query() - e.g. {\"query\": \"SELECT ...\"} "
                    "for a SQL source, {\"tag_name\": \"Roll Speed\"} for PI, "
                    "{\"command\": [\"GET\", \"key\"]} for Redis."
                ),
            },
        },
        "required": ["source_name", "query_payload"],
    }
    coordinate_timeout = 15.0

    def contribute(self, ctx: HarnessContext, request: dict) -> None:
        """
        Self-filter on ``params["source_name"]``; if this worker has it locally, run the query and reply.

        Sends nothing if this worker doesn't have `source_name` in its
        own local config - not even a "not applicable" message. For a
        `mode: broker` entry, relays via `HarnessContext.query_data_source`
        instead of querying in-process.
        """
        params = request.get("params", {})
        source_name = params["source_name"]
        query_payload = params.get("query_payload", {})

        entry = local_config.find_source(source_name)
        if entry is None:
            return  # not mine - send nothing, not even a "not applicable" message

        try:
            if entry.get("mode") == "broker":
                result = ctx.query_data_source(source_name, query_payload)
            else:
                connector = local_config.build_connector(entry)
                result = connector.query(query_payload)
            status, payload = "ok", result
        except Exception as exc:
            status, payload = "error", str(exc)

        ctx.buses.local_bus.Send(request["coordinator"], {
            "type": _RESULT_MSG_TYPE,
            "request_id": request["request_id"],
            "from": ctx.agent_id,
            "status": status,
            "payload": payload,
        })

    def coordinate(self, ctx: HarnessContext, request: dict, workers: list[str]) -> dict:
        """Run `_coordinate`, then release the router queue for this `request_id` regardless of outcome."""
        try:
            return self._coordinate(ctx, request)
        finally:
            ctx.buses.local_router.forget(request["request_id"])

    def _coordinate(self, ctx: HarnessContext, request: dict) -> dict:
        """
        Wait for the first worker holding ``source_name`` to reply, and return its answer.

        Returns
        -------
        dict
            ``{"status": "ok", "result": <query result>, "detail": ...}``
            from the first responder; ``{"status": "error", "detail": ..., "retryable": ...}``
            if the responder's query failed, or if nothing responds
            within `coordinate_timeout` (treated as a real "not found",
            not retryable - not a timeout waiting on stragglers, since
              nobody in the dispatched group has this source locally).
        """
        source_name = request.get("params", {}).get("source_name", "<unknown>")
        deadline = time.time() + self.coordinate_timeout
        while time.time() < deadline:
            if ctx.cancelled.is_set():
                return {"status": "error", "detail": "cancelled", "retryable": False}
            msg = ctx.buses.local_router.receive_for(request["request_id"], timeout=1)
            if not msg:
                continue
            body = msg.get("body", {})
            if body.get("type") == _RESULT_MSG_TYPE:
                if body.get("status") == "ok":
                    return {
                        "status": "ok",
                        "result": body.get("payload"),
                        "detail": f"answered by {body.get('from')}",
                    }
                return {
                    "status": "error",
                    "detail": f"{body.get('from')} failed to query {source_name!r}: {body.get('payload')}",
                    "retryable": True,
                }

        if ctx.cancelled.is_set():
            return {"status": "error", "detail": "cancelled", "retryable": False}

        # Silence, not a timeout waiting on stragglers - nobody in the
        # dispatched group has this source locally. A real "not found",
        # not something a retry would fix.
        return {
            "status": "error",
            "detail": f"no worker holding data source {source_name!r} responded within {self.coordinate_timeout}s",
            "retryable": False,
        }
