"""
CancellationToken / CancellationRegistry — worker-side tracking of
in-flight requests, so a skill_cancel message (sent when the head
supersedes an attempt with a retry - see head.run_skill()) can actually
reach whatever's running for that request_id.

A CancellationToken gives a skill two ways to notice cancellation, both
fully opt-in - a skill that never touches either behaves exactly as if
this didn't exist:

  - .event: a plain threading.Event, for code that already loops and
    polls periodically (see median.py/sum.py's ready-signal wait loops) -
    just add `and not ctx.cancelled.is_set()` alongside the existing
    deadline check.
  - .on_cancel(fn): register fn to run *immediately*, on a new thread, the
    moment cancellation fires - for a skill doing one monolithic blocking
    call (e.g. a slow DB query) with no natural checkpoint to poll a flag
    at. fn is expected to force that call to unblock early (e.g. close the
    connection it's using) - the token has no idea how to do that itself,
    only the skill does. Registering after cancellation already fired
    still runs fn right away, rather than silently losing it - the same
    "doesn't matter which came first" guarantee router.py's on_key() gives
    for message delivery, applied here to cancellation instead.

A token also tracks skill_name, started_at, and an opt-in progress dict a
skill's coordinate() can update as it goes (e.g. ready_count/expected_count
- see median.py/sum.py). This is what makes CancellationRegistry.snapshot()
- and so a check-in reply's grounding (dialogue.py's context_fn) - genuinely
specific instead of "here are some request IDs that exist": a real-LLM test
found that a bare ID list gave a coordinator nothing to reason about beyond
"this is still going," so it hedged rather than answering confidently. See
snapshot()'s docstring for the shape this now reports.

The registry (request_id -> CancellationToken) is worker-local, one per
worker process, constructed once at startup (see worker.start_dispatch()).
A token is created the moment a dispatch message starts being handled -
before contribute()/coordinate() runs at all, the same "register early"
discipline router.py/MessageRouter already relies on, so a skill_cancel
arriving at nearly the same moment as the original dispatch is never
missed.
"""
import threading
import time
from typing import Callable


class CancellationToken:
    """
    Per-request cancellation signal, with two fully opt-in ways for a skill to notice it.

    A skill that never touches `event` or `on_cancel` behaves exactly as
    if this class didn't exist.

    Parameters
    ----------
    skill_name : str, optional
        Name of the skill this token is scoped to, surfaced via
        `CancellationRegistry.snapshot`.

    Attributes
    ----------
    event : threading.Event
        Set the moment cancellation fires. For code that already loops
        and polls periodically (see `skills.median`/`skills.sum`'s
        ready-signal wait loops) - just add
        ``and not ctx.cancelled.is_set()`` alongside the existing
        deadline check.
    skill_name : str
    started_at : float
        `time.time()` at construction.
    """

    def __init__(self, skill_name: str = ""):
        self.event = threading.Event()
        self.skill_name = skill_name
        self.started_at = time.time()
        self._callbacks: list[Callable[[], None]] = []
        self._progress: dict = {}
        self._lock = threading.Lock()

    def on_cancel(self, fn: Callable[[], None]) -> None:
        """
        Register `fn` to run immediately, on a new thread, the moment cancellation fires.

        For a skill doing one monolithic blocking call (e.g. a slow DB
        query) with no natural checkpoint to poll a flag at. `fn` is
        expected to force that call to unblock early (e.g. close the
        connection it's using) - the token has no idea how to do that
        itself, only the skill does. Registering after cancellation
        already fired still runs `fn` right away, rather than silently
        losing it.

        Parameters
        ----------
        fn : callable
            Called with no arguments, on a new daemon thread.
        """
        with self._lock:
            already_cancelled = self.event.is_set()
            if not already_cancelled:
                self._callbacks.append(fn)
        if already_cancelled:
            threading.Thread(target=fn, daemon=True).start()

    def cancel(self) -> None:
        """Set `event` and fire every registered `on_cancel` callback, each on its own daemon thread. Idempotent."""
        with self._lock:
            if self.event.is_set():
                return  # already cancelled - callbacks already ran, don't run them twice
            self.event.set()
            callbacks = list(self._callbacks)
        for fn in callbacks:
            threading.Thread(target=fn, daemon=True).start()

    def update_progress(self, **kwargs) -> None:
        """
        Record real, observable progress on this request.

        Called by a skill's `coordinate` loop as it goes - e.g.
        ``token.update_progress(ready_count=2, expected_count=3)`` each
        time a contributor signals ready. Purely additive/opt-in: a
        skill that never calls this just reports `skill_name`/elapsed
        via `CancellationRegistry.snapshot`, no progress fields - still
        far more specific than a bare id, but not as sharp as a skill
        that actively reports where it's at.

        Parameters
        ----------
        **kwargs
            Arbitrary progress fields (e.g. `ready_count`,
            `expected_count`), merged into this token's progress dict.
        """
        with self._lock:
            self._progress.update(kwargs)

    def progress_snapshot(self) -> dict:
        """
        Returns
        -------
        dict
            A copy of the progress fields set via `update_progress`.
        """
        with self._lock:
            return dict(self._progress)


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


def describe_in_flight(snapshot: dict) -> str:
    """
    Format `CancellationRegistry.snapshot`'s output into explicit, unambiguous sentences.

    Not a raw dict/JSON dump - for use in an LLM prompt (see
    ``__main__.py``'s worker ``context_fn``, `dialogue`'s
    ``_system_prompt``). Found via a real-LLM test: a bare list of
    request ids left a coordinator with nothing concrete to reason from,
    so it hedged instead of answering directly. Real numbers - elapsed
    time, ready-vs-expected counts, when a skill reports them (see
    `HarnessContext.report_progress`) - let it answer specifically
    instead.

    Parameters
    ----------
    snapshot : dict
        As returned by `CancellationRegistry.snapshot`.

    Returns
    -------
    str
        One sentence per in-flight request, or a fixed "nothing in
        flight" sentence if `snapshot` is empty.
    """
    if not snapshot:
        return "Nothing currently in flight - no requests being coordinated or contributed to right now."
    lines = []
    for request_id, info in snapshot.items():
        skill = info.get("skill") or "an unnamed skill"
        elapsed = info.get("elapsed_seconds")
        elapsed_str = f"started {elapsed}s ago" if elapsed is not None else "start time unknown"
        ready = info.get("ready_count")
        expected = info.get("expected_count")
        if ready is not None and expected is not None:
            remaining = expected - ready
            progress_str = (
                f"{ready} of {expected} contributors have checked in, {remaining} still pending"
                if remaining > 0 else f"all {expected} of {expected} contributors have checked in"
            )
        else:
            progress_str = "no contributor progress reported yet"
        lines.append(f"- Request {request_id}: coordinating {skill!r}, {elapsed_str}, {progress_str}.")
    return "\n".join(lines)
