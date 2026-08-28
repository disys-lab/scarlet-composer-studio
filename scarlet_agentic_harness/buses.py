"""
Two-channel Messenger setup, per scarlet-composer-studio's own documented
pattern (docs/concepts/two-channel.md): every agent opens exactly two
Messenger buses - a global bus (head <-> all agents in the campaign) and a
local bus (peer-to-peer within one device group, no head involved).

This module only wires the two Messenger instances together with a shared
capability-reporting call - it deliberately does not add a third bus or
change the underlying two-channel semantics scarlets already defines.
"""
from scarlets.messaging import Messenger

from scarlet_agentic_harness.config import HarnessConfig


class Buses:
    """Holds an agent's global_bus and local_bus Messenger instances."""

    def __init__(self, config: HarnessConfig):
        self.config = config
        self.global_bus = Messenger(
            config.head_bus,
            agentId=config.agent_id,
            description=(
                "Campaign-wide coordination bus: task dispatch from the head, "
                "capability discovery, skill_result replies."
            ),
        )
        self.local_bus = Messenger(
            config.device_group,
            agentId=config.agent_id,
            description=(
                "Device-group-local peer bus: contributor<->coordinator "
                "handshakes for a skill invocation, without routing through "
                "the head."
            ),
        )

    def report_status(self, capabilities: list[str], extra: dict | None = None) -> None:
        """
        Report this agent's status/capabilities on both buses, matching the
        shape from DESIGN_v3.md section 8.3 exactly (status/role/capabilities/
        data_sources/mcp_tools/device_group/node_address/instance_id) so this
        harness's agents show up correctly in scarlet-composer-studio's own
        Agents dashboard (GatherStatus display), not just to each other.
        """
        status = {
            "status": "online",
            "role": self.config.role,
            "capabilities": list(capabilities),
            "data_sources": [],
            "mcp_tools": [],
            "device_group": self.config.device_group,
            "node_address": self.config.node_address,
        }
        if extra:
            status.update(extra)
        self.global_bus.ReportStatus(status)
        self.local_bus.ReportStatus(status)

    def gather_workers(self) -> dict:
        """
        Survey currently-registered agents on the global bus (head's own
        capability-discovery step - see DESIGN_v3.md section 8.5: the head
        calls GatherStatus() to enumerate online workers before routing a
        task). Excludes this agent's own record.
        """
        records = self.global_bus.GatherStatus()
        records.pop(self.config.agent_id, None)
        return {
            agent_id: rec
            for agent_id, rec in records.items()
            if rec.get("role") == "worker"
        }
