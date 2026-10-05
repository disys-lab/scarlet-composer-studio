"""
ListSourcesSkill — a coordination skill that answers the one question the fleet
currently cannot: "what data sources exist, anywhere?"

This skill is the entry point that makes `query_feature` usable without the
caller being told source names out of band. Since `list_tags` requires a
`source_name`, which is the thing a caller is trying to discover, this skill
breaks the chicken-and-egg problem by having each worker report what it holds,
and the coordinator aggregates those reports into a complete inventory.
"""
import time

from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.skills.base import Skill
from scarlet_agentic_harness import local_config
from scarlet_agentic_harness import data_profile

_RESULT_MSG_TYPE = "source_inventory"


class ListSourcesSkill(Skill):
    """
    Coordinate workers to discover all data sources in the fleet.

    This skill is the FIRST call to make when the caller does not already know
    source names. Each worker reports what sources it holds (name, type,
    description, shape, numeric_columns) by combining `local_config.describe_sources()`
    and `ctx.data_profiles`. The coordinator collects all reports and returns a
    unified inventory.

    Returns
    -------
    dict
        On success: ``{"status": "ok", "result": {<agent_id>: [<source dicts>], ...},
        "total_sources": <int>, "replied": <int>, "expected": <int>,
        "detail": <str>}``.
        On error: ``{"status": "error", "detail": <str>, "retryable": <bool>}``.
    """

    name = "list_sources"
    description = (
        "Discover all data sources in the fleet. This is the FIRST call to make "
        "when the caller does not already know source names. Each worker reports "
        "what sources it holds (name, type, description, shape, numeric_columns). "
        "The coordinator aggregates these reports into a unified inventory. "
        "The output of this skill feeds `query_feature`'s `source_name` parameter."
    )
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    coordinate_timeout = 30.0

    def contribute(self, ctx: HarnessContext, request: dict) -> None:
        """
        Report what this worker holds.

        Combine two sources of truth:
        - `local_config.describe_sources()` -> list of redacted dicts with
          keys name/type/mode/description. This is the ONLY safe thing to
          expose off-worker; never send `path` or any credential field.
        - `ctx.data_profiles` -> per-source "shape" and "numeric_columns".

        Call `data_profile.refresh_if_stale(ctx.data_profiles)` first, so an
        inventory never advertises sources the config no longer has.

        Send ONE message to `request["coordinator"]` on `ctx.buses.local_bus`
        with the complete source inventory. Send it even when the worker has
        no sources (empty list) — silence cannot be told apart from a crashed
        worker.

        A source present in describe_sources() but absent from data_profiles
        must still be listed, with shape None. It exists; it just failed to
        profile, and hiding it would make it undiscoverable forever.
        """
        # Refresh profiles to ensure we don't advertise stale data
        data_profile.refresh_if_stale(ctx.data_profiles)

        # Get sources from config (redacted, safe to share)
        sources_from_config = local_config.describe_sources()

        # Build a lookup for profiles by source name
        profiles_by_name = {}
        if hasattr(ctx, "data_profiles") and isinstance(ctx.data_profiles, dict):
            for src_name, profile in ctx.data_profiles.items():
                if isinstance(src_name, str):
                    profiles_by_name[src_name] = profile

        # Build the list of sources to report
        sources_to_report = []
        for src in sources_from_config:
            src_name = src.get("name")
            profile = profiles_by_name.get(src_name, {})

            # Extract shape and numeric_columns from profile, with defaults
            shape = profile.get("shape")
            if not isinstance(shape, (list, tuple)) or len(shape) != 2:
                shape = None
            else:
                # Ensure shape is a list of two integers
                try:
                    shape = [int(shape[0]), int(shape[1])]
                except (ValueError, TypeError):
                    shape = None

            numeric_columns = profile.get("numeric_columns", [])
            if not isinstance(numeric_columns, list):
                numeric_columns = []

            # Build the source dict with only safe fields
            source_dict = {
                "name": src.get("name"),
                "type": src.get("type"),
                "description": src.get("description"),
                "shape": shape,
                "numeric_columns": numeric_columns,
            }
            sources_to_report.append(source_dict)

        # Send the inventory to the coordinator
        ctx.buses.local_bus.Send(
            request["coordinator"],
            {
                "type": _RESULT_MSG_TYPE,
                "request_id": request["request_id"],
                "from": ctx.agent_id,
                "sources": sources_to_report,
            },
        )

    def coordinate(self, ctx: HarnessContext, request: dict, workers: list[str]) -> dict:
        """
        Run `_coordinate`, then release the router queue for this `request_id`.

        The router queue is always released in a finally block regardless of
        outcome to prevent queue leaks.
        """
        try:
            return self._coordinate(ctx, request, workers)
        finally:
            ctx.buses.local_router.forget(request["request_id"])

    def _coordinate(self, ctx: HarnessContext, request: dict, workers: list[str]) -> dict:
        """
        Wait for every worker's source inventory, aggregate results, and return
        a unified inventory.

        Parameters
        ----------
        ctx : HarnessContext
            The execution context.
        request : dict
            The request dictionary with "request_id" and "params".
        workers : list[str]
            List of worker agent IDs expected to respond.

        Returns
        -------
        dict
            On success: ``{"status": "ok", "result": {<agent_id>: [<source dicts>], ...},
            "total_sources": <int>, "replied": <int>, "expected": <int>,
            "detail": <str>}``.
            On error: ``{"status": "error", "detail": <str>, "retryable": <bool>}``.
        """
        result: dict[str, list[dict]] = {}
        expected = len(workers)

        # Report progress before anything has checked in
        ctx.report_progress(ready_count=0, expected_count=expected)
        deadline = time.time() + self.coordinate_timeout

        while len(result) < expected and time.time() < deadline:
            if ctx.cancelled.is_set():
                return {"status": "error", "detail": "cancelled", "retryable": False}

            msg = ctx.buses.local_router.receive_for(request["request_id"], timeout=1)
            if not msg:
                continue

            body = msg.get("body", {})
            if body.get("type") == _RESULT_MSG_TYPE:
                agent_id = body.get("from")
                if agent_id:
                    sources = body.get("sources", [])
                    if not isinstance(sources, list):
                        sources = []
                    result[agent_id] = sources
                    ctx.report_progress(ready_count=len(result), expected_count=expected)

        if ctx.cancelled.is_set():
            return {"status": "error", "detail": "cancelled", "retryable": False}

        # Count total sources across all workers
        total_sources = sum(len(sources) for sources in result.values())

        # Build detail message
        replied = len(result)
        if replied == 0:
            detail = "no workers responded"
        else:
            detail = f"{total_sources} sources across {replied} workers"

        # Determine retryability
        if replied == 0:
            # Nobody responded — retryable
            return {
                "status": "error",
                "detail": detail,
                "retryable": True,
            }

        # If responders exist but NO source anywhere, that's a valid result (not an error)
        # A fleet legitimately holding no data is a true answer, not a failure
        return {
            "status": "ok",
            "result": result,
            "total_sources": total_sources,
            "replied": replied,
            "expected": expected,
            "detail": detail,
        }
