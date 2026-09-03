"""
TimeoutWatcher — one background thread scanning scheduled deadlines,
instead of one thread per pending wait.

MessageRouter.on_key() lets a caller register interest in a key and return
immediately (see router.py). Some callers also need "if nothing arrives
within N seconds, do something else instead" (head.run_skill()'s async
form watching for a coordinator reply; a future check-in conversation
watching for a response). The naive way to add a per-registration timeout
is a dedicated thread per registration that sleeps and then fires - but
that means thread count grows with concurrent in-flight waits, unbounded,
which is exactly the kind of growth worth avoiding (see the worker
concurrency docstring in worker.py for the same concern applied to
dispatch). A single thread that periodically scans all scheduled deadlines
and fires whichever ones have passed keeps thread count fixed regardless
of how many waits are in flight at once.

This module has no knowledge of MessageRouter, keys' meaning, or callbacks'
purpose - it is a generic "call this if nothing cancels it by this time"
primitive, reused by router.py (which owns the actual double-fire
prevention: cancelling a scheduled timeout when the real message arrives,
and clearing the real callback when a timeout fires instead - see
MessageRouter.on_key()'s integration).
"""
import threading
import time
from typing import Callable


class TimeoutWatcher:
    """
    One background thread scanning scheduled deadlines, instead of one thread per pending wait.

    Generic "call this if nothing cancels it by this time" primitive -
    has no knowledge of `MessageRouter`, keys' meaning, or callbacks'
    purpose. `MessageRouter` owns the actual double-fire prevention
    (cancelling a scheduled timeout when the real message arrives, and
    clearing the real callback when a timeout fires instead).

    Parameters
    ----------
    scan_interval : float, optional
        Seconds between deadline scans - a real floor on how fast any
        scheduled timeout can fire (a deadline shorter than this doesn't
        fire any sooner, it just waits for the next scan). Default `0.5`.
    """

    def __init__(self, scan_interval: float = 0.5):
        self._scan_interval = scan_interval
        self._deadlines: dict[object, tuple[float, Callable[[], None]]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def schedule(self, key, deadline: float, on_timeout: Callable[[], None]) -> None:
        """
        Fire `on_timeout`, on a new thread, if `cancel(key)` isn't called before `deadline`.

        Parameters
        ----------
        key : object
        deadline : float
            Absolute `time.time()` value, not a duration.
        on_timeout : callable
            Called with no arguments if the deadline passes uncancelled.
        """
        with self._lock:
            self._deadlines[key] = (deadline, on_timeout)

    def cancel(self, key) -> None:
        """
        Remove a scheduled timeout.

        Call once whatever the timeout was guarding against happened for
        a real reason (e.g. the awaited message actually arrived).

        Parameters
        ----------
        key : object
        """
        with self._lock:
            self._deadlines.pop(key, None)

    def stop(self) -> None:
        """Stop the scanning thread, joining it (up to 2s)."""
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        """Scan `_deadlines` every `_scan_interval` seconds until `stop` is called, firing anything past its deadline."""
        while not self._stop.is_set():
            time.sleep(self._scan_interval)
            now = time.time()
            fired: list[Callable[[], None]] = []
            with self._lock:
                for key, (deadline, on_timeout) in list(self._deadlines.items()):
                    if now >= deadline:
                        fired.append(on_timeout)
                        del self._deadlines[key]
            for on_timeout in fired:
                threading.Thread(target=on_timeout, daemon=True).start()
