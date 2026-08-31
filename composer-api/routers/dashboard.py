"""
/api/dashboard/stats — landing-page summary.

Deliberately scoped to data that actually exists for scarlet-composer:
agent count (real GatherStatus() call, same as routers/agents.py),
scarlet-definition count (scan `scarlet_definition_*` keys - the same
convention scarletcomposer/Scarlets.py's View tab already uses), and a
Redis connectivity check. No fabricated "platform services" card the way
Gustavo's dashboard has one - composer doesn't manage services that way.
"""
import logging

from fastapi import APIRouter
from scarlets.utils.ScarletUtils import redisConnect

from bus_registry import AGENT_ID, get_messenger, known_buses

router = APIRouter()

DEFAULT_BUS = "head-agent"  # matches Agents.py's own default


@router.get("/stats")
async def get_stats():
    redis_ok = True
    redis_error = None
    try:
        r = redisConnect()
        r.ping()
    except Exception as exc:
        redis_ok = False
        redis_error = str(exc)

    agent_count = 0
    if redis_ok:
        try:
            records = get_messenger(DEFAULT_BUS).GatherStatus()
            agent_count = sum(1 for agent_id in records if agent_id != AGENT_ID)
        except Exception as exc:
            logging.error(f"dashboard agent count failed: {exc}")

    scarlet_count = 0
    if redis_ok:
        try:
            # Exclude scarlet_definition_{bus} for any bus composer-api has
            # itself constructed a Messenger for - that entry is a side
            # effect of composer-api's own read traffic (see
            # bus_registry.py), not a real scarlet definition.
            excluded = {f"scarlet_definition_{b}" for b in known_buses()}
            scarlet_count = sum(
                1 for key in r.scan_iter(match="scarlet_definition_*")
                if key.decode("utf-8") not in excluded
            )
        except Exception as exc:
            logging.error(f"dashboard scarlet count failed: {exc}")

    return {
        "error": False,
        "response": {
            "redis_ok": redis_ok,
            "redis_error": redis_error,
            "agent_count": agent_count,
            "agent_bus": DEFAULT_BUS,
            "scarlet_count": scarlet_count,
        },
    }
