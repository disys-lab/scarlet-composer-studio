"""Turns a result-callback back into something a caller can wait on."""
import threading


class ResultBox:
    """
    Catches one `on_result` callback and lets a caller block until it lands.

    `run_skill` returns `None` and delivers its answer later by calling a
    callback, because the work happens on other processes and the reply
    arrives on another thread. A caller that genuinely needs to wait has to
    bridge the two: this holds the result and the event that signals it.

    Callable with one argument, so it passes straight as `on_result`.

    Examples
    --------
    >>> box = ResultBox()
    >>> run_skill(skill, params, config, buses, box)
    >>> box.wait(timeout=30)
    True
    >>> box.result
    {'status': 'ok'}
    """

    def __init__(self):
        self._done = threading.Event()
        self.result: dict | None = None

    def __call__(self, result: dict) -> None:
        """Store `result` and release anyone waiting."""
        self.result = result
        self._done.set()

    def wait(self, timeout: float) -> bool:
        """
        Block until a result arrives.

        Parameters
        ----------
        timeout : float
            Seconds to wait.

        Returns
        -------
        bool
            True if a result arrived, False if the wait timed out.
        """
        return self._done.wait(timeout=timeout)
