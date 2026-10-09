"""The callback a router schedules for one pending reply's timeout."""


class TimeoutHandler:
    """
    Fires a router key's timeout, but only if the real reply has not landed.

    A real message and its timeout can race. Whoever pops the callback
    under the lock is the one that actually happened, and only the winner
    acts: if the reply already popped it, `on_timeout` must not fire,
    because the wait was satisfied for a real reason.

    Callable with no arguments, so it drops straight into
    `TimeoutWatcher.schedule`.

    Parameters
    ----------
    router : MessageRouter
        Owns the lock and the callback table this consults.
    key : object
        The pending-reply key this timeout belongs to.
    on_timeout : callable or None
        Invoked if this timeout wins the race. `None` means the key is
        simply dropped.
    """

    def __init__(self, router, key, on_timeout):
        self._router = router
        self._key = key
        self._on_timeout = on_timeout

    def __call__(self) -> None:
        """Pop the callback under the lock; fire `on_timeout` only if we won."""
        with self._router._lock:
            had_callback = self._router._callbacks.pop(self._key, None) is not None
        if had_callback and self._on_timeout is not None:
            self._on_timeout()
