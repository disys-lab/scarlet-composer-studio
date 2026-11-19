"""A cancellation token that is never cancelled, for contexts built without one."""
import threading


class _NoopCancellation:
    """
    Stand-in for a real `CancellationToken` on a context that isn't
    scoped to one in-flight, cancellable request (e.g. `run_skill`'s own
    top-level `ctx`, used only for `coordinator_for` calls).

    `cancelled` reports "not cancelled" (a fresh, unset `Event`) and
    `on_cancel` is a silent no-op, so code written against
    `ctx.cancelled`/`ctx.on_cancel` doesn't need to branch on whether a
    real token exists.

    Attributes
    ----------
    event : threading.Event
        A fresh, never-set event.
    """

    def __init__(self):
        self.event = threading.Event()

    def on_cancel(self, fn) -> None:
        """No-op. Parameters: `fn` (callable), ignored."""
        pass

    def update_progress(self, **kwargs) -> None:
        """No-op. Parameters: arbitrary keyword progress fields, ignored."""
        pass
