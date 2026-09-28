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

from bus_registry import AGENT_ID, bus_exists, get_messenger

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
    # Gated on bus_exists for the same reason /api/agents is: DEFAULT_BUS is
    # a hardcoded guess at a conventional name, and constructing a Messenger
    # for it would *create* that bus - on any deployment that doesn't happen
    # to use this exact name, the dashboard would mint a permanent, empty
    # scarlet purely by being loaded. A bus nobody has created has no agents
    # on it, so 0 is the honest answer.
    if redis_ok and bus_exists(DEFAULT_BUS):
        try:
            records = get_messenger(DEFAULT_BUS).GatherStatus()
            agent_count = sum(1 for agent_id in records if agent_id != AGENT_ID)
        except Exception as exc:
            logging.error(f"dashboard agent count failed: {exc}")

    scarlet_count = 0
    if redis_ok:
        try:
            # Counts every scarlet_definition_* key, with no exclusions.
            # This used to subtract the buses composer-api had itself
            # constructed a Messenger for, because that construction created
            # those entries as a side effect of read traffic. It can no
            # longer do that: every Messenger built here is now gated on the
            # definition already existing (see bus_registry.py), so the only
            # definitions present are ones real agents created. Keeping the
            # exclusion would now subtract *those*, undercounting the real
            # total.
            scarlet_count = sum(1 for _ in r.scan_iter(match="scarlet_definition_*"))
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
