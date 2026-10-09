"""A cooperative cancellation flag shared between a request and its workers."""
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
