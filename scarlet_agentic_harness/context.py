"""
HarnessContext — bundles an agent's config and buses, and constructs
request-scoped Mapper/Federator instances. Passed into every Skill handler
so a skill never has to touch env vars or bus wiring directly.
"""
from scarlets.core.Mapper import Mapper
from scarlets.formulations.Federator import Federator

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig


class HarnessContext:
    def __init__(self, config: HarnessConfig, buses: Buses):
        self.config = config
        self.buses = buses

    @property
    def agent_id(self) -> str:
        return self.config.agent_id

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
