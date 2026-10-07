"""
ListTagsSkill — the dynamic counterpart to a data source's static
`description`: given a source_name a caller already knows (from its own
config, the directory, or a peer's dialogue reply), returns what that
source's connector reports right now via Connector.list_tags() (see
data_connectors/base.py) - real schema, not a human-written guess.

Same shape as query_feature.py exactly (self-filtering contribute(),
first-response-wins coordinate()) - see that module's own docstring for
the full rationale, unchanged here. The one real difference: mode:
broker entries aren't supported yet. query_feature has
ctx.query_data_source() to relay a query through a broker's existing
/query HTTP route; there's no equivalent /list_tags route on the broker
today, so contribute() raises a clear, honest error for a matching
mode: broker entry rather than silently returning nothing (which would
be indistinguishable from "no worker has this source" - a real,
different case coordinate() already reports separately). Extending the
broker's own HTTP surface for this is real, separate work, not built
here.
"""
import time

from scarlet_agentic_harness import local_config
from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.skills.base import Skill

_RESULT_MSG_TYPE = "list_tags_result"


class ListTagsSkill(Skill):
    """
    Dynamic counterpart to a data source's static `description`.

    Given a `source_name` a caller already knows (from its own config,
    the directory, or a peer's dialogue reply), returns what that
    source's connector reports right now via
    `data_connectors.base.Connector.list_tags` - real schema, not a
    human-written guess.

    Same shape as `skills.query_feature.QueryFeatureSkill` exactly
    (self-filtering `contribute`, first-response-wins `coordinate`). One
    real difference: `mode: broker` entries aren't supported yet - there's
    no ``/list_tags`` HTTP route on the broker today (unlike `query`), so
    `contribute` raises a clear, honest error for a matching `mode:
    broker` entry rather than silently returning nothing.
    """

    name = "list_tags"
    description = (
        "List the real, live tags/columns a data source actually has right now - "
        "not the hand-written description, the actual schema. Use this once you "
        "already know the exact source_name to ask about."
    )
    parameters = {
        "type": "object",
        "properties": {
            "source_name": {
                "type": "string",
                "description": "Must match a `name` in the answering worker's own local config.",
            },
        },
        "required": ["source_name"],
    }
    coordinate_timeout = 15.0

    def contribute(self, ctx: HarnessContext, request: dict) -> None:
        """
        Self-filter on ``params["source_name"]``; if this worker has it locally, list its real tags and reply.

        Sends nothing if this worker doesn't have `source_name` in its
        own local config - not even a "not applicable" message.
        """
        source_name = request.get("params", {})["source_name"]

        entry = local_config.find_source(source_name)
        if entry is None:
            return  # not mine - send nothing, not even a "not applicable" message

        try:
            if entry.get("mode") == "broker":
                raise NotImplementedError(
                    f"list_tags is not yet supported for mode: broker sources ({source_name!r})"
                )
            connector = local_config.build_connector(entry)
            result = connector.list_tags()
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
            ``{"status": "ok", "result": <tags>, "detail": ...}`` from
            the first responder; ``{"status": "error", "detail": ..., "retryable": ...}``
            if the responder failed to introspect, or if nothing
            responds within `coordinate_timeout` (treated as a real "not
            found", not retryable).
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
                    "detail": f"{body.get('from')} failed to list tags for {source_name!r}: {body.get('payload')}",
                    "retryable": True,
                }

        if ctx.cancelled.is_set():
            return {"status": "error", "detail": "cancelled", "retryable": False}

        return {
            "status": "error",
            "detail": f"no worker holding data source {source_name!r} responded within {self.coordinate_timeout}s",
            "retryable": False,
        }
