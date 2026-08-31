"""
HarnessContext — bundles an agent's config and buses, and constructs
request-scoped Mapper/Federator instances. Passed into every Skill handler
so a skill never has to touch env vars or bus wiring directly.
"""
import threading

from scarlets.core.Mapper import Mapper
from scarlets.formulations.Federator import Federator

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.cancellation import CancellationToken
from scarlet_agentic_harness.config import HarnessConfig


class _NoopCancellation:
    """Stand-in for a real CancellationToken when a context isn't scoped to
    one in-flight, cancellable request (e.g. run_skill()'s own top-level
    ctx, used only for coordinator_for() calls - see head.py). .cancelled
    reports "not cancelled" (a fresh, unset Event) and .on_cancel() is a
    silent no-op, so code written against ctx.cancelled/ctx.on_cancel()
    doesn't need to branch on whether a token exists."""

    def __init__(self):
        self.event = threading.Event()

    def on_cancel(self, fn) -> None:
        pass

    def update_progress(self, **kwargs) -> None:
        pass


class HarnessContext:
    def __init__(self, config: HarnessConfig, buses: Buses, cancellation: "CancellationToken | None" = None):
        self.config = config
        self.buses = buses
        self._cancellation = cancellation if cancellation is not None else _NoopCancellation()

    @property
    def agent_id(self) -> str:
        return self.config.agent_id

    @property
    def cancelled(self) -> threading.Event:
        """Set once this request has been cancelled (see cancellation.py) -
        for code that already loops/polls a deadline, add
        `and not ctx.cancelled.is_set()` alongside it."""
        return self._cancellation.event

    def on_cancel(self, fn) -> None:
        """Register fn to run immediately, on a new thread, the moment this
        request is cancelled - for a skill doing one blocking call with no
        natural checkpoint to poll a flag at. See cancellation.py."""
        self._cancellation.on_cancel(fn)

    def report_progress(self, **kwargs) -> None:
        """
        Opt-in: let a skill's coordinate() report real, specific progress
        (e.g. `ctx.report_progress(ready_count=2, expected_count=3)`) as it
        goes - this is what makes a check-in reply grounded in genuinely
        useful detail rather than just "this request exists" (see
        cancellation.py's CancellationToken.update_progress()). A no-op
        when this context isn't scoped to a cancellable, tracked request.
        """
        self._cancellation.update_progress(**kwargs)

    def mapper(self, name: str, description: str = "") -> Mapper:
        """
        Construct a Mapper scoped to `name`. Callers (skills) must pass a
        name unique to the in-flight request (e.g. f"{skill.name}_{request_id}")
        - a shared/static name would let two concurrent invocations of the
        same skill collide on each other's keys.
        """
        return Mapper(name, description=description)

    def federator(self, name: str, op) -> Federator:
        """
        Construct a Federator scoped to `name`, same per-request naming rule
        as mapper(). Note: Federator's real __init__ signature (scarlets
        source, not the README) takes no `description` kwarg - only
        scarletName and op.
        """
        return Federator(name, op)
