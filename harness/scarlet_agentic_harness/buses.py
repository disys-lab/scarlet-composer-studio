"""
Two-channel Messenger setup, per scarlet-composer-studio's own documented
pattern (docs/concepts/two-channel.md): every agent opens exactly two
Messenger buses - a global bus (head <-> all agents in the campaign) and a
local bus (peer-to-peer within one device group, no head involved).

This module only wires the two Messenger instances together with a shared
capability-reporting call - it deliberately does not add a third bus or
change the underlying two-channel semantics scarlets already defines.

Each bus also gets a MessageRouter (router.py) wrapped around it. From the
moment a Buses is constructed, the router is the *only* caller of that
bus's Receive() - see router.py's docstring for why sharing Receive()
across concurrent waiters is unsafe with scarlets' actual FIFO-with-ack-on-
read transport. Nothing in this module or its callers should call
global_bus.Receive()/local_bus.Receive() directly again.
"""
import time

from scarlets.messaging import Messenger

from scarlet_agentic_harness import local_config
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.router import MessageRouter


def _global_bus_key(msg: dict):
    """
    `MessageRouter` key function for the global bus.

    Only ``skill_result`` replies are request-scoped waits on the global
    bus - a `run_skill` call registers as the waiter for its own
    `request_id` and expects exactly one reply. ``skill_contribute``/
    ``skill_coordinate`` dispatch messages also carry a `request_id`, but
    nothing is ever waiting to *receive* one of those - they're
    unsolicited from the receiving agent's perspective, so they must
    always go to `default_handler` regardless of that shared field name.
    Same for ``agent_message`` traffic (`dialogue`) - it has no
    `request_id` at all, so it already falls through to
    `default_handler` here too.

    Parameters
    ----------
    msg : dict
        A message as delivered by `Messenger.Receive`.

    Returns
    -------
    object or None
        The `request_id` to route this message to a waiter by, or `None`
        to send it to `default_handler` instead.
    """
    body = msg.get("body", {})
    if body.get("type") == "skill_result":
        return body.get("request_id")
    return None


def _local_bus_key(msg: dict):
    """
    `MessageRouter` key function for the local bus.

    Every skill readiness signal on the local bus (see
    `skills.median`/`skills.sum`) is request-scoped by `request_id`.
    ``agent_message`` traffic (`dialogue`) can also ride the local bus
    for peer-to-peer conversation - like on the global bus, it must
    always go to `default_handler` regardless of whether a matching
    `conversation_id` is being watched for. `request_id` is simply
    absent from an `agent_message` body, so this already falls through
    correctly - spelled out explicitly rather than left as a coincidence
    of differing field names.

    Parameters
    ----------
    msg : dict
        A message as delivered by `Messenger.Receive`.

    Returns
    -------
    object or None
        The `request_id` to route this message to a waiter by, or `None`
        to send it to `default_handler` instead.
    """
    body = msg.get("body", {})
    if body.get("type") == "agent_message":
        return None
    return body.get("request_id")


class Buses:
    """
    Holds an agent's `global_bus`/`local_bus` `Messenger` instances and the `MessageRouter` wrapping each one.

    From the moment a `Buses` is constructed, each router is the *only*
    caller of its bus's `Receive` - nothing else should call
    `global_bus.Receive`/`local_bus.Receive` directly (see `router` for
    why sharing `Receive` across concurrent waiters is unsafe with
    scarlets' actual FIFO-with-ack-on-read transport).

    Parameters
    ----------
    config : HarnessConfig

    Attributes
    ----------
    config : HarnessConfig
    global_bus : scarlets.messaging.Messenger
        Campaign-wide coordination bus: task dispatch from the head,
        capability discovery, `skill_result` replies.
    local_bus : scarlets.messaging.Messenger
        Device-group-local peer bus: contributor<->coordinator
        handshakes for a skill invocation, without routing through the
        head.
    global_router : MessageRouter
    local_router : MessageRouter
    """

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
        self.global_router = MessageRouter(
            self.global_bus, key_fn=_global_bus_key, timeout_scan_interval=config.timeout_scan_interval,
        )
        self.local_router = MessageRouter(
            self.local_bus, key_fn=_local_bus_key, timeout_scan_interval=config.timeout_scan_interval,
        )

    def report_status(self, capabilities: list[str], extra: dict | None = None) -> None:
        """
        Report this agent's status/capabilities on both buses.

        Matches the shape from ``DESIGN_v3.md`` section 8.3 exactly
        (``status``/``role``/``capabilities``/``data_sources``/
        ``mcp_tools``/``device_group``/``node_address``/``instance_id``)
        so this harness's agents show up correctly in
        scarlet-composer-studio's own Agents dashboard, not just to each
        other.

        Parameters
        ----------
        capabilities : list of str
            Skill names this agent can dispatch to.
        extra : dict or None, optional
            Additional fields merged into the reported status.

        Notes
        -----
        `data_sources` is read fresh from `local_config.describe_sources`
        on every call (redacted - name/type/mode/description only, never
        a credential field) rather than passed in by the caller - this
        way a periodic re-report (see ``__main__.py``) picks up a
        hand-edited ``~/.scarlet/config.yaml`` without either side
        needing to remember to re-derive it each time.
        """
        status = {
            "status": "online",
            "role": self.config.role,
            "capabilities": list(capabilities),
            "data_sources": local_config.describe_sources(),
            "mcp_tools": [],
            "device_group": self.config.device_group,
            "node_address": self.config.node_address,
        }
        if extra:
            status.update(extra)
        self.global_bus.ReportStatus(status)
        self.local_bus.ReportStatus(status)

    def gather_workers(self, max_staleness: float = 60.0) -> dict:
        """
        Survey currently-registered `"worker"`-role agents on the global bus.

        The head's own capability-discovery step (`DESIGN_v3.md` section
        8.5): the head calls `Messenger.GatherStatus` to enumerate online
        workers before routing a task. Excludes this agent's own record.

        Parameters
        ----------
        max_staleness : float, optional
            Exclude any worker record whose `ts` (last write to the
            registry) is older than this many seconds. Default `60.0`
            (2x the heartbeat interval, generous slack for one missed
            beat). This matters because scarlets' own registry never
            expires entries on its own - `Messenger.Register`/
            `ReportStatus` just overwrite a Redis key with no TTL, and
            only a live heartbeat thread (every 30s) keeps a real
            agent's `ts` moving forward. Without this filter, a worker
            whose process has actually died would still show up as
            online forever, making `head.run_skill`'s retry-on-failure
            pointless for that case - every retry would survey the same
            stale record and dispatch to the same dead worker again.

        Returns
        -------
        dict
            Worker records keyed by `agent_id`, excluding this agent and
            anything staler than `max_staleness`.
        """
        records = self.global_bus.GatherStatus()
        records.pop(self.config.agent_id, None)
        now = time.time()
        return {
            agent_id: rec
            for agent_id, rec in records.items()
            if rec.get("role") == "worker" and (now - rec.get("ts", 0)) <= max_staleness
        }
