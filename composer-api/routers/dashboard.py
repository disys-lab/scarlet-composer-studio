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

from fastapi import APIRouter, Query
from scarlets.utils.ScarletUtils import redisConnect

from bus_registry import AGENT_ID, bus_exists, get_messenger
from status import agent_health

router = APIRouter()

# Only a fallback for a caller that names no bus. It is a conventional name
# from scarlets' own examples, not one any real deployment necessarily uses -
# the harness derives its bus from HEAD_BUS, or f"{APP_ID}_headagent" when
# that is unset, and neither produces this. Counting against it
# unconditionally is why this card reported "0 agents on bus head-agent" on
# deployments with a perfectly healthy fleet: it was counting a bus nobody
# had ever joined. The Agents page knows the real bus - the operator chooses
# it there and it persists - so the UI passes that value here.
DEFAULT_BUS = "head-agent"


@router.get("/stats")
async def get_stats(bus: str = Query(DEFAULT_BUS, description="Messenger bus to count agents on")):
    redis_ok = True
    redis_error = None
    try:
        r = redisConnect()
        r.ping()
    except Exception as exc:
        redis_ok = False
        redis_error = str(exc)

    agent_count = 0
    # Gated on bus_exists for the same reason /api/agents is: this name now
    # arrives from a query parameter, and constructing a Messenger for an
    # arbitrary string *creates* that bus - so an unrecognised name would
    # mint a permanent, empty scarlet purely because someone loaded the
    # dashboard. A bus nobody has created has no agents on it, so 0 is the
    # honest answer.
    if redis_ok and bus_exists(bus):
        try:
            records = get_messenger(bus).GatherStatus()
            # Stale records are excluded, which this previously did not do -
            # the Agents page has always applied the same rule via
            # agent_health, so a dead fleet showed as greyed out there while
            # still being counted as live here. status.py exists precisely so
            # "what counts as stale" is defined once; this endpoint simply
            # never used it.
            agent_count = sum(
                1 for agent_id, record in records.items()
                if agent_id != AGENT_ID and agent_health(record) != "stale"
            )
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
