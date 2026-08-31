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

The registry (request_id -> CancellationToken) is worker-local, one per
worker process, constructed once at startup (see worker.start_dispatch()).
A token is created the moment a dispatch message starts being handled -
before contribute()/coordinate() runs at all, the same "register early"
discipline router.py/MessageRouter already relies on, so a skill_cancel
arriving at nearly the same moment as the original dispatch is never
missed.
"""
import threading
from typing import Callable


class CancellationToken:
    def __init__(self):
        self.event = threading.Event()
        self._callbacks: list[Callable[[], None]] = []
        self._lock = threading.Lock()

    def on_cancel(self, fn: Callable[[], None]) -> None:
        with self._lock:
            already_cancelled = self.event.is_set()
            if not already_cancelled:
                self._callbacks.append(fn)
        if already_cancelled:
            threading.Thread(target=fn, daemon=True).start()

    def cancel(self) -> None:
        with self._lock:
            if self.event.is_set():
                return  # already cancelled - callbacks already ran, don't run them twice
            self.event.set()
            callbacks = list(self._callbacks)
        for fn in callbacks:
            threading.Thread(target=fn, daemon=True).start()


class CancellationRegistry:
    def __init__(self):
        self._tokens: dict[str, CancellationToken] = {}
        self._lock = threading.Lock()

    def create(self, request_id: str) -> CancellationToken:
        token = CancellationToken()
        with self._lock:
            self._tokens[request_id] = token
        return token

    def cancel(self, request_id: str) -> None:
        """No-op if request_id isn't tracked - a cancel for a request this
        worker never saw, or already finished, is a normal race (see
        head.py), not an error."""
        with self._lock:
            token = self._tokens.get(request_id)
        if token is not None:
            token.cancel()

    def forget(self, request_id: str) -> None:
        with self._lock:
            self._tokens.pop(request_id, None)
