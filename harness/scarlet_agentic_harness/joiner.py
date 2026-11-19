"""Waits for a set of concurrent skill results to all arrive."""
import threading
from typing import Callable


class _Joiner:
    """
    Collect N async tool-call results for one turn, then run `on_all_done` exactly once.

    Results are keyed by call id in the turn's original order - not
    completion order, which varies now that each tool call dispatches
    independently instead of one after another. The decrement-and-check
    is done atomically under one lock so exactly one thread ever
    observes "that was the last one", regardless of which call's result
    arrives last.

    Parameters
    ----------
    calls : list of dict
        This turn's tool calls, each with an ``"id"`` key.
    on_all_done : callable
        ``(results_by_id: dict) -> None``, called once every call has a
        result, with results in `calls`' original order.
    """

    def __init__(self, calls: list[dict], on_all_done: Callable[[dict], None]):
        self._calls = calls
        self._on_all_done = on_all_done
        self._results: dict[str, dict] = {}
        self._remaining = len(calls)
        self._lock = threading.Lock()

    def submit(self, call_id: str, result: dict) -> None:
        """
        Record one call's result; run `on_all_done` if this was the last one.

        Parameters
        ----------
        call_id : str
        result : dict
        """
        with self._lock:
            self._results[call_id] = result
            self._remaining -= 1
            done = self._remaining == 0
        if done:
            ordered = {call["id"]: self._results[call["id"]] for call in self._calls}
            self._on_all_done(ordered)
