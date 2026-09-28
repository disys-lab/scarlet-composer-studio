"""
/api/agents — live agent registry for a Messenger bus, plus each agent's
current in-flight activity.

GET /api/agents?bus=scarlet-agent-tutorial_headagent

Replaces scarletcomposer/pages/Agents.py's own hand-rolled Redis scan
(`{bus_name}:reg:*` via a locally-defined `_gather_agents()`) with a real
call to Messenger.GatherStatus() (scarlets/messaging/Messenger.py) - the
actual primitive this data comes from. The Streamlit page reimplemented
that scan instead of calling it; this is the same query, just through the
real API instead of a second, parallel implementation of it.

The bus name is a query parameter and therefore untrusted: see
bus_registry.bus_exists() for why it is checked before anything is
constructed, and what constructing a Messenger for an arbitrary string
used to leave behind.

─── Activity ──────────────────────────────────────────────────────────────

Agents report where their in-flight activity lives (`activity_mapper` in
their status record - see the harness's __main__.py), so this endpoint
never needs to be told a mapper name and the UI never has to ask for one.
It collects the *distinct* names advertised across the agents on this bus
and reads each, which is what makes this correct when they differ.

They differ whenever ACTIVITY_MAPPER is left unset and the agents are
separate Gustavo apps: the harness falls back to f"{app_id}_activity", and
Gustavo sets APP_ID per app. Reading only the first name found, or
assuming a single mapper, would silently show a partial fleet. Every entry
is keyed by agent_id and agent ids are unique, so merging the mappers is a
plain dict union with no possibility of collision.
"""
import logging

from fastapi import APIRouter, Query

from bus_registry import AGENT_ID, bus_exists, get_mapper, get_messenger
from status import agent_health

router = APIRouter()


def _activity_by_agent(records: dict) -> dict:
    """
    Read every distinct activity Mapper these agents advertise.

    Parameters
    ----------
    records : dict
        `Messenger.GatherStatus()` output, keyed by agent id.

    Returns
    -------
    dict
        Per-agent activity (``{"in_flight": {...}, "count": n}``), keyed
        by agent id. Agents that advertise no mapper, and mappers that
        fail to read, are simply absent - this is best-effort visibility,
        exactly as `observability.snapshot` treats it, and must never
        take the agent listing down with it.
    """
    names = {
        record.get("activity_mapper")
        for record in records.values()
        if record.get("activity_mapper")
    }
    merged: dict = {}
    for name in names:
        try:
            gathered, ok, _exc = get_mapper(name).AllGather()
            if ok and gathered:
                merged.update(gathered)
        except Exception as exc:
            logging.warning(f"activity read failed for mapper {name!r}: {exc}")
    return merged


@router.get("")
async def list_agents(bus: str = Query("head-agent", description="Messenger bus name")):
    try:
        # A bus nobody has created has no agents on it. Returning empty
        # rather than constructing one keeps a typo from minting a
        # permanent scarlet - see bus_registry.bus_exists().
        if not bus_exists(bus):
            return {"error": False, "response": {"bus": bus, "agents": [], "unknown_bus": True}}

        messenger = get_messenger(bus)
        records = messenger.GatherStatus()
        activity = _activity_by_agent(records)
        agents = [
            {
                "agent_id": agent_id,
                "instance_id": record.get("instance_id"),
                "scarlet_name": record.get("scarlet_name"),
                "ts": record.get("ts"),
                "health": agent_health(record),
                "capabilities": record.get("capabilities", []),
                "data_sources": record.get("data_sources", []),
                # None distinguishes "publishes no activity at all" - a
                # head, or an agent on an image predating activity_mapper
                # reporting - from "is publishing, currently idle", which
                # is an empty in_flight. The UI renders those differently.
                "activity": activity.get(agent_id),
                "raw": record,
            }
            for agent_id, record in records.items()
            if agent_id != AGENT_ID  # exclude composer-api's own registration
        ]
        agents.sort(key=lambda a: a["agent_id"])
        return {"error": False, "response": {"bus": bus, "agents": agents, "unknown_bus": False}}
    except Exception as exc:
        logging.error(f"list_agents failed: {exc}")
        return {"error": True, "response": str(exc)}
