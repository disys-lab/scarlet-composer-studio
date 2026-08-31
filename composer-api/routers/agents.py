"""
/api/agents — live agent registry for a Messenger bus.

GET /api/agents?bus=head-agent

Replaces scarletcomposer/pages/Agents.py's own hand-rolled Redis scan
(`{bus_name}:reg:*` via a locally-defined `_gather_agents()`) with a real
call to Messenger.GatherStatus() (scarlets/messaging/Messenger.py) - the
actual primitive this data comes from. The Streamlit page reimplemented
that scan instead of calling it; this is the same query, just through the
real API instead of a second, parallel implementation of it.
"""
import logging

from fastapi import APIRouter, Query

from bus_registry import AGENT_ID, get_messenger
from status import agent_health

router = APIRouter()


@router.get("")
async def list_agents(bus: str = Query("head-agent", description="Messenger bus name")):
    try:
        messenger = get_messenger(bus)
        records = messenger.GatherStatus()
        agents = [
            {
                "agent_id": agent_id,
                "instance_id": record.get("instance_id"),
                "scarlet_name": record.get("scarlet_name"),
                "ts": record.get("ts"),
                "health": agent_health(record),
                "capabilities": record.get("capabilities", []),
                "data_sources": record.get("data_sources", []),
                "raw": record,
            }
            for agent_id, record in records.items()
            if agent_id != AGENT_ID  # exclude composer-api's own registration
        ]
        agents.sort(key=lambda a: a["agent_id"])
        return {"error": False, "response": {"bus": bus, "agents": agents}}
    except Exception as exc:
        logging.error(f"list_agents failed: {exc}")
        return {"error": True, "response": str(exc)}
