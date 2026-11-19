"""
AgreeRepresentationSkill — a coordination skill that runs before sum/median
to resolve the one thing that now stops those skills from running: workers
holding different numeric column sets, which makes their matrices
un-aggregatable.

This skill asks each worker to report the numeric columns it actually holds
(unioned across all its data profiles) and the total row count. The
coordinator computes the INTERSECTION of all reported column lists — this is
the deterministic, physically-aggregatable representation. Because the
agreed representation is supposed to be reasoned about, not merely computed,
the coordinator also runs a bounded discussion: it asks each peer to
voluntarily agree to the intersection or explain why it cannot. Objections
are recorded but do not cause failure — the intersection remains the only
shape that can physically aggregate.
"""
import threading
import time

from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.skills.base import Skill
from scarlet_agentic_harness import data_profile

_READY_MSG_TYPE = "representation_proposal"


class AgreeRepresentationSkill(Skill):
    """
    Coordinate workers to agree on a common numeric column representation.

    This skill is run BEFORE sum/median when workers may hold different
    columns. Each worker reports its numeric columns and row counts; the
    coordinator computes the INTERSECTION of all reported column lists —
    the deterministic, physically-aggregatable representation. A bounded
    discussion is then run to allow workers to voluntarily agree or object.

    Returns
    -------
    dict
        On success: ``{"status": "ok", "result": <agreed columns>,
        "proposals": {...}, "objections": {...}, "replied": <int>,
        "expected": <int>, "detail": <str>}``.
        On error: ``{"status": "error", "detail": <str>, "retryable": <bool>}``.
    """

    name = "agree_representation"
    description = (
        "Coordinate workers to agree on a common numeric column representation "
        "before running sum/median. Each worker reports its numeric columns and "
        "row counts; the coordinator computes the INTERSECTION of all reported "
        "column lists — the deterministic, physically-aggregatable representation. "
        "A bounded discussion is run to allow workers to voluntarily agree or "
        "object. Returns the agreed column list those skills should then be given."
    )
    parameters = {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": (
                    "A plain-language statement of what measurements are wanted, "
                    "e.g. \"vibration and torque readings\". Used to give the "
                    "discussion context. Do NOT name a data source, a file or a "
                    "column."
                ),
            },
        },
        "required": [],
    }
    coordinate_timeout = 30.0
    discussion_timeout = 25.0

    def contribute(self, ctx: HarnessContext, request: dict) -> None:
        """
        Report what this worker actually holds.

        For each profile in `ctx.data_profiles`, extract "numeric_columns"
        (list of str), "rows" (int) and "shape". Send ONE message to
        `request["coordinator"]` on `ctx.buses.local_bus` with the union of
        numeric columns (sorted) and total rows across all profiles.

        Send the message even if the worker has no profiles (empty list) —
        silence is indistinguishable from a crashed worker.
        """
        # Same staleness guard as local_matrix: proposing columns from a
        # profile the config no longer matches would have the fleet agree on
        # a representation nobody can actually read.
        data_profile.refresh_if_stale(ctx.data_profiles)

        # Union numeric columns across all profiles, then sort
        all_columns = set()
        total_rows = 0

        profiles = getattr(ctx, "data_profiles", {})
        if isinstance(profiles, dict):
            for profile in profiles.values():
                cols = profile.get("numeric_columns", [])
                if isinstance(cols, list):
                    all_columns.update(cols)
                rows = profile.get("rows", 0)
                if isinstance(rows, int):
                    total_rows += rows

        columns = sorted(all_columns)

        ctx.buses.local_bus.Send(
            request["coordinator"],
            {
                "type": _READY_MSG_TYPE,
                "request_id": request["request_id"],
                "from": ctx.agent_id,
                "columns": columns,
                "rows": total_rows,
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
        Wait for every worker's readiness signal, compute the intersection of
        reported columns, optionally run a bounded discussion, and return the
        agreed representation.

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
            On success: ``{"status": "ok", "result": <agreed columns>,
            "proposals": {...}, "objections": {...}, "replied": <int>,
            "expected": <int>, "detail": <str>}``.
            On error: ``{"status": "error", "detail": <str>, "retryable": <bool>}``.
        """
        proposals: dict[str, list[str]] = {}
        expected = len(workers)

        # Report progress before anything has checked in
        ctx.report_progress(ready_count=0, expected_count=expected)
        deadline = time.time() + self.coordinate_timeout

        while len(proposals) < expected and time.time() < deadline:
            if ctx.cancelled.is_set():
                return {"status": "error", "detail": "cancelled", "retryable": False}

            msg = ctx.buses.local_router.receive_for(request["request_id"], timeout=1)
            if not msg:
                continue

            body = msg.get("body", {})
            if body.get("type") == _READY_MSG_TYPE:
                agent_id = body.get("from")
                if agent_id:
                    proposals[agent_id] = body.get("columns", [])
                    ctx.report_progress(ready_count=len(proposals), expected_count=expected)

        if ctx.cancelled.is_set():
            return {"status": "error", "detail": "cancelled", "retryable": False}

        # Check for missing workers
        missing = set(workers) - set(proposals.keys())
        if missing:
            return {
                "status": "error",
                "detail": f"workers did not report ready in time: {sorted(missing)}",
                "retryable": True,
            }

        # Compute intersection of all reported columns
        if proposals:
            common_columns = set(proposals[next(iter(proposals))])
            for cols in proposals.values():
                common_columns.intersection_update(cols)
            intersection = sorted(common_columns)
        else:
            intersection = []

        # Prepare discussion context
        params = request.get("params", {})
        objective = params.get("objective", "the requested measurements")
        rows_info = {
            agent_id: f"{len(cols)} columns, {proposals[agent_id]} rows"
            for agent_id, cols in proposals.items()
        }

        # Build discussion message
        table_lines = []
        for agent_id, cols in sorted(proposals.items()):
            rows = proposals[agent_id]
            table_lines.append(f"- {agent_id}: {len(cols)} columns, {rows} rows")
        table_text = "\n".join(table_lines)

        discussion_message = (
            f"Objective: {objective}\n\n"
            "Table of reported columns and rows:\n"
            f"{table_text}\n\n"
            f"Computed intersection: {intersection}\n\n"
            "Please reply with either 'AGREE' or a short reason you cannot use "
            "those columns."
        )

        # Decide whether to run discussion
        objections: dict[str, str] = {}
        replied = len(proposals)

        if ctx.dialogue is not None and len(proposals) >= 2:
            # Run bounded discussion
            replies_received = threading.Event()
            reply_list: list[tuple[str, str]] = []
            reply_lock = threading.Lock()

            def on_reply(content: str, sender: str) -> None:
                with reply_lock:
                    reply_list.append((sender, content))
                    if len(reply_list) >= len(proposals) - 1:  # exclude coordinator if it's a peer
                        replies_received.set()

            # Start discussions with all peers except the coordinator itself
            for peer_id in proposals.keys():
                if peer_id != ctx.agent_id:
                    ctx.dialogue.start(peer_id, discussion_message, on_reply)

            # Wait for replies or timeout
            replies_received.wait(timeout=self.discussion_timeout)

            # Process replies
            for peer_id, reply_text in reply_list:
                if "AGREE" not in reply_text.upper():
                    objections[peer_id] = reply_text

            # Update replied count to reflect actual replies received
            replied = len(reply_list)

        # Determine final result
        if not intersection:
            # Build detailed error listing each worker's columns
            details = []
            for agent_id, cols in sorted(proposals.items()):
                details.append(f"{agent_id}: {cols}")
            return {
                "status": "error",
                "detail": f"no common columns across workers:\n" + "\n".join(details),
                "retryable": False,
            }

        # Build detail message
        detail = (
            f"Agreed representation: {intersection} "
            f"({replied} of {expected} workers replied, {len(objections)} objections)"
        )

        return {
            "status": "ok",
            "result": intersection,
            "proposals": proposals,
            "objections": objections,
            "replied": replied,
            "expected": expected,
            "detail": detail,
        }
