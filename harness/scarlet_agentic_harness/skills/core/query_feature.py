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

from scarlet_agentic_harness import data_profile
from scarlet_agentic_harness import local_config
from scarlet_agentic_harness import local_matrix
from scarlet_agentic_harness.skills import predicate
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
            "objective": {
                "type": "string",
                "description": (
                    "A plain-language statement of what data is wanted, e.g. \"recent "
                    "turbine health readings\". Prefer this: each worker picks its own "
                    "source and writes its own SQL, and every worker holding something "
                    "relevant answers. Do not pair it with source_name."
                ),
            },
            "source_name": {
                "type": "string",
                "description": (
                    "Exact source to read, as reported by list_sources. Use only when you "
                    "already know the name; only the worker holding it answers. Requires "
                    "query_payload."
                ),
            },
            "query_payload": {
                "type": "object",
                "description": (
                    "Connector-specific query, passed straight through to the "
                    "matching connector's query(). "
                    # CSV/Excel called out first and by name. The previous
                    # wording offered {"query": "SELECT ..."} only "for a SQL
                    # source", and a model reading that does not necessarily
                    # class a CSV as SQL - observed: it guessed a column
                    # selector, {"cpu_pct": true, "heartbeat": true}, got an
                    # error, and only then sent the SELECT. That cost one
                    # wasted turn per source, which across four sources was
                    # enough to exhaust converse's 5-turn budget and fail the
                    # whole conversation. The table name is spelled out for
                    # the same reason: it is always `data`, never the file or
                    # source name, and there is no way to infer that.
                    "For a CSV or Excel source: {\"query\": \"SELECT col1, col2 "
                    "FROM data\"} - the table is ALWAYS named `data`, whatever "
                    "the source is called. "
                    "For a SQL database: {\"query\": \"SELECT ... FROM "
                    "real_table\"}. "
                    "For PI: {\"tag_name\": \"Roll Speed\"}. "
                    "For Redis: {\"command\": [\"GET\", \"key\"]}."
                ),
            },
            "conditions": dict(
                predicate.CONDITIONS_SCHEMA,
                description=predicate.CONDITIONS_SCHEMA["description"] + (
                    " Only valid with the objective form: give an objective and "
                    "no query_payload, so each worker builds its own query and "
                    "appends the filter to it. Passing conditions together with "
                    "query_payload is refused rather than ignored, because a "
                    "dropped filter returns the unfiltered answer and nothing "
                    "about it looks wrong."
                ),
            ),
        },
        "required": [],
    }
    coordinate_timeout = 15.0

    def _reject(self, ctx: HarnessContext, request: dict,
                source_name: str | None, detail: str) -> None:
        """
        Reply with an error rather than staying silent or answering anyway.

        Silence is this skill's normal "not mine" signal, so it cannot also
        mean "I was asked something I can't honour" - the caller would read
        a refusal as an absence. Anything the worker declines to do has to
        come back as a visible error.

        Parameters
        ----------
        ctx : HarnessContext
        request : dict
        source_name : str or None
        detail : str
            Message for the caller, naming what was refused and why.
        """
        ctx.buses.local_bus.Send(request["coordinator"], {
            "type": _RESULT_MSG_TYPE,
            "request_id": request["request_id"],
            "from": ctx.agent_id,
            "source_name": source_name,
            "status": "error",
            "payload": detail,
        })

    def contribute(self, ctx: HarnessContext, request: dict) -> None:
        """
        Self-filter on ``params["source_name"]``; if this worker has it locally, run the query and reply.

        Sends nothing if this worker doesn't have `source_name` in its
        own local config - not even a "not applicable" message. For a
        `mode: broker` entry, relays via `HarnessContext.query_data_source`
        instead of querying in-process.
        """
        params = request.get("params", {})
        source_name = params.get("source_name")
        query_payload = params.get("query_payload") or {}

        # A filter can only be applied to SQL this worker builds itself. Given
        # a caller-written query there is nowhere safe to put it - the query
        # may already carry its own WHERE, or an ORDER BY / LIMIT the clause
        # would land behind - and appending blind would produce a syntax error
        # at best and a different question at worst.
        #
        # So refuse, loudly. Quietly dropping the filter is the one option
        # that must not happen: the caller would get the unfiltered answer
        # believing it was filtered, which is a plausible number and not an
        # error. Same reasoning as the predicate being settled once and
        # applied identically everywhere.
        if params.get("conditions") and query_payload:
            self._reject(ctx, request, source_name,
                         "conditions cannot be applied to a caller-supplied "
                         "query_payload - pass an objective and let each worker "
                         "build its own query, or fold the filter into the SQL "
                         "you are passing")
            return

        if source_name:
            # Explicit form, unchanged: the caller already knows the name, so
            # this worker answers only if it holds that exact source.
            entry = local_config.find_source(source_name)
            if entry is None:
                return  # not mine - send nothing, not even a "not applicable" message
        else:
            # Objective form. The head named nothing, so this worker picks its
            # own source and writes its own SQL - the same two functions
            # sum/median use, rather than a second implementation.
            #
            # Unlike the explicit form, every worker holding any data answers.
            # coordinate() collects them all rather than taking the first,
            # because "whoever has something matching this" has no single
            # right answer.
            objective = params.get("objective", "all available measurements")
            data_profile.refresh_if_stale(ctx.data_profiles)
            chosen = local_matrix.choose_source(ctx, objective)
            if chosen is None:
                return  # nothing local to offer - stay silent, as above
            entry = local_config.find_source(chosen)
            if entry is None:
                return
            source_name = chosen
            if not query_payload:
                try:
                    sql = local_matrix.generate_sql(ctx, chosen, objective)
                    # The filter is appended only to SQL this worker wrote
                    # itself. See the guard above for why it is refused rather
                    # than ignored when the caller supplied their own query.
                    conditions = params.get("conditions")
                    if conditions:
                        sql = sql + predicate.build_where(
                            conditions, ctx.data_profiles.get(chosen) or {})
                    query_payload = {"query": sql}
                except Exception as exc:
                    ctx.buses.local_bus.Send(request["coordinator"], {
                        "type": _RESULT_MSG_TYPE,
                        "request_id": request["request_id"],
                        "from": ctx.agent_id,
                        "source_name": chosen,
                        "status": "error",
                        "payload": f"could not generate a query: {exc}",
                    })
                    return

        # A broker source is not in this worker's own profiles, so there is
        # nothing to validate the filter's column against - and an unvalidated
        # column is how a filter silently matches nothing or errors deep in
        # someone else's engine. Refuse, with the same reasoning as above.
        if params.get("conditions") and entry.get("mode") == "broker":
            self._reject(ctx, request, source_name,
                         "conditions are not supported against a broker source - "
                         "this worker has no profile for it and cannot check the "
                         "filter column exists")
            return

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
            "source_name": source_name,
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
        params = request.get("params", {})
        source_name = params.get("source_name")
        # Two shapes, because the two questions are different. Named: one
        # worker holds that source, so the first real answer IS the answer.
        # Objective: "whoever has something matching this" has no single
        # right responder, so wait out the window and return them all.
        collect_all = not source_name
        gathered: dict[str, dict] = {}
        failures: dict[str, str] = {}

        deadline = time.time() + self.coordinate_timeout
        while time.time() < deadline:
            if ctx.cancelled.is_set():
                return {"status": "error", "detail": "cancelled", "retryable": False}
            msg = ctx.buses.local_router.receive_for(request["request_id"], timeout=1)
            if not msg:
                continue
            body = msg.get("body", {})
            if body.get("type") != _RESULT_MSG_TYPE:
                continue

            if collect_all:
                who = body.get("from")
                if body.get("status") == "ok":
                    gathered[who] = {"source": body.get("source_name"),
                                     "result": body.get("payload")}
                else:
                    failures[who] = body.get("payload")
                continue

            if body.get("status") == "ok":
                return {
                    "status": "ok",
                    "result": body.get("payload"),
                    "source_name": body.get("source_name"),
                    "detail": f"answered by {body.get('from')}",
                }
            return {
                "status": "error",
                "detail": f"{body.get('from')} failed to query {source_name!r}: {body.get('payload')}",
                "retryable": True,
            }

        if collect_all:
            if not gathered and not failures:
                return {
                    "status": "error",
                    "detail": "no worker offered any data for that objective",
                    "retryable": False,
                }
            return {
                "status": "ok",
                "result": gathered,
                "failures": failures,
                "detail": (f"{len(gathered)} worker(s) answered"
                           + (f", {len(failures)} failed" if failures else "")),
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
