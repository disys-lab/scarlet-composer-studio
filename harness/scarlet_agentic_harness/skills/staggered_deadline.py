"""A coordinate() deadline that extends while the fleet is still answering."""
import time


class StaggeredDeadline:
    """
    A deadline that extends while contributions keep arriving.

    A flat timeout has to be either generous enough for the slowest worker
    or short enough to notice a hang, and it cannot be both. This starts at
    `base` and moves out by `extension` each time another worker reports,
    never past `ceiling` seconds from the start. A fleet still making
    progress gets more time; a silent one does not, and a wedged worker
    still fails at the ceiling.

    Parameters
    ----------
    base : float
        Initial wait, in seconds.
    extension : float
        Added when a new contribution arrives.
    ceiling : float
        Hard limit measured from construction.
    expected : int
        How many contributions completion needs. Once that many have
        arrived the deadline stops extending - the last arrival should not
        buy time nobody is waiting on.

    Examples
    --------
    >>> deadline = StaggeredDeadline(15.0, 10.0, 45.0, expected=4)
    >>> while len(ready) < 4 and deadline.still_waiting(len(ready)):
    ...     ...
    """

    def __init__(self, base: float, extension: float, ceiling: float,
                 expected: int):
        now = time.time()
        self._deadline = now + base
        self._ceiling = now + ceiling
        self._extension = extension
        self._expected = expected
        self._seen = 0

    def still_waiting(self, count: int) -> bool:
        """
        Extend if `count` has grown, then report whether time remains.

        Parameters
        ----------
        count : int
            Contributions received so far.

        Returns
        -------
        bool
            True while there is still time left to wait.
        """
        if count > self._seen:
            self._seen = count
            if count < self._expected:
                # max() against the current deadline is load-bearing: a
                # worker replying early must never pull the deadline in.
                # Written as a bare min(ceiling, now + extension) it did
                # exactly that - a reply at t=1s cut a 15s deadline to 11s -
                # causing spurious timeouts, retries, and notebooks that ran
                # until their cell limit killed them.
                self._deadline = min(
                    self._ceiling,
                    max(self._deadline, time.time() + self._extension))
        return time.time() < self._deadline
