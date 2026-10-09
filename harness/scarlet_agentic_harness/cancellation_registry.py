"""Tracks the in-flight cancellation tokens for one agent."""
import threading
import time

from scarlet_agentic_harness.cancellation_token import CancellationToken


class CancellationRegistry:
    """
    Worker-local `request_id -> CancellationToken` bookkeeping.

    One per worker process, constructed once at startup (see
    `worker.start_dispatch`). A token is created the moment a dispatch
    message starts being handled - before `contribute`/`coordinate` runs
    at all, the same "register early" discipline `router.MessageRouter`
    already relies on, so a ``skill_cancel`` arriving at nearly the same
    moment as the original dispatch is never missed.

    Parameters
    ----------
    activity_mapper : scarlets.core.Mapper.Mapper or None, optional
    agent_id : str or None, optional
        If both `activity_mapper` and `agent_id` are given, every
        `create`/`forget` also publishes this worker's current in-flight
        request detail (the same shape `snapshot` returns) to a shared
        Mapper (see `observability`), so the same bookkeeping this
        registry already does doesn't need a second, separate tracker
        for live-activity visibility. Left as `None` (the default) means
        no publishing - callers that only care about cancellation, not
        observability, pay nothing extra.
    """

    def __init__(self, activity_mapper=None, agent_id: str | None = None):
        self._tokens: dict[str, CancellationToken] = {}
        self._lock = threading.Lock()
        self._activity_mapper = activity_mapper
        self._agent_id = agent_id

    def create(self, request_id: str, skill_name: str = "") -> CancellationToken:
        """
        Create and register a new `CancellationToken` for `request_id`.

        Parameters
        ----------
        request_id : str
        skill_name : str, optional

        Returns
        -------
        CancellationToken
        """
        token = CancellationToken(skill_name=skill_name)
        with self._lock:
            self._tokens[request_id] = token
        self._publish()
        return token

    def cancel(self, request_id: str) -> None:
        """
        Cancel the token registered for `request_id`, if any.

        No-op if `request_id` isn't tracked - a cancel for a request
        this worker never saw, or already finished, is a normal race
        (see `head`), not an error.

        Parameters
        ----------
        request_id : str
        """
        with self._lock:
            token = self._tokens.get(request_id)
        if token is not None:
            token.cancel()

    def forget(self, request_id: str) -> None:
        """
        Remove `request_id`'s token from the registry (does not cancel it first).

        Parameters
        ----------
        request_id : str
        """
        with self._lock:
            self._tokens.pop(request_id, None)
        self._publish()

    def snapshot(self) -> dict[str, dict]:
        """
        Rich per-request status for every currently-tracked request.

        Not just a bare list of ids - this is what a check-in reply
        (`dialogue`'s ``context_fn``) actually grounds itself in. A real
        LLM test showed why that matters: told only "here are some
        request ids that exist," the model had nothing concrete to
        reason from and hedged; given skill name, real elapsed time, and
        (when a skill reports it) a ready/expected count, it answered
        specifically instead.

        Returns
        -------
        dict
            ``{request_id: {"skill": ..., "elapsed_seconds": ..., **progress}}``,
            where `progress` is whatever fields the skill passed to
            `CancellationToken.update_progress`.
        """
        with self._lock:
            tokens = dict(self._tokens)
        now = time.time()
        return {
            request_id: {
                "skill": token.skill_name,
                "elapsed_seconds": round(now - token.started_at, 1),
                **token.progress_snapshot(),
            }
            for request_id, token in tokens.items()
        }

    def _publish(self) -> None:
        """Publish the current `snapshot` to `_activity_mapper`, if configured. No-op otherwise."""
        if self._activity_mapper is None:
            return
        snapshot = self.snapshot()
        self._activity_mapper.Map(
            {"in_flight": snapshot, "count": len(snapshot)}, key=self._agent_id,
        )
