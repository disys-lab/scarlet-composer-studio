"""
/api/conversations — what the agents actually said to each other.

GET /api/conversations?bus=<head bus>&local_bus=<device group>
GET /api/conversations/{conv_id}?bus=...&local_bus=...

The Logging page already shows `RedisLogger` output, but that is a flat
chronological stream with ten minutes of retention, in which several
concurrent requests interleave into something unreadable. This reads the
messages themselves - which persist in the recipients' inboxes until the
bus's own TTL - and puts them back into the shape they had: one
conversation, the head's reasoning through it, and the dispatch traffic
each decision caused, nested under the decision that caused it.

See conversations.py for how that reconstruction works and why the
`dispatch` event is the only thing that makes it possible.

Both buses are read. Dispatch and check-ins ride the head bus; contributor
handshakes ride the device-group bus, and a stalled skill often shows up
only in the second - which is exactly the case a reader is usually trying
to understand.
"""
import logging

from fastapi import APIRouter, Query

import conversations as conv_lib
from bus_registry import bus_exists

router = APIRouter()


def _buses(bus: str, local_bus: str | None) -> list[str]:
    """
    The buses to read, dropping any that do not exist.

    Unlike /api/agents this does not need to *construct* anything - reading
    inbox keys touches no Messenger - so an unknown name here cannot create
    a scarlet. It is still filtered, so a typo yields an empty view rather
    than a confusing partial one.
    """
    names = [b for b in (bus, local_bus) if b]
    return [b for b in names if bus_exists(b)]


@router.get("")
async def list_conversations(
    bus: str = Query(..., description="Head bus (HEAD_BUS on the agents)"),
    local_bus: str | None = Query(None, description="Device-group bus (DEVICE_GROUP)"),
    limit: int = Query(50, ge=1, le=500),
):
    try:
        buses = _buses(bus, local_bus)
        if not buses:
            return {"error": False, "response": {
                "conversations": [], "unattributed": [], "buses": [], "unknown_bus": True,
            }}
        index = conv_lib.collect(buses)
        return {"error": False, "response": {
            "conversations": conv_lib.list_conversations(index, limit=limit),
            # Dispatch traffic we cannot place in a conversation - shown
            # rather than hidden, since it is the normal state of a fleet
            # with PUBLISH_REASONING off or agents on an older image.
            "unattributed": conv_lib.unattributed(index)[:limit],
            "buses": buses,
            "unknown_bus": False,
        }}
    except Exception as exc:
        logging.error(f"list_conversations failed: {exc}")
        return {"error": True, "response": str(exc)}


@router.get("/{conv_id}")
async def get_conversation(
    conv_id: str,
    bus: str = Query(..., description="Head bus (HEAD_BUS on the agents)"),
    local_bus: str | None = Query(None, description="Device-group bus (DEVICE_GROUP)"),
):
    try:
        buses = _buses(bus, local_bus)
        if not buses:
            return {"error": True, "response": f"no such bus: {bus!r}"}
        index = conv_lib.collect(buses)
        if conv_id not in index["by_conv"]:
            # Distinguishable from an empty conversation: the messages may
            # simply have aged out with the bus's TTL, which is expected
            # rather than an error.
            return {"error": True, "response": (
                f"conversation {conv_id!r} not found on {buses} - it may have "
                f"expired with the bus's own TTL"
            )}
        return {"error": False, "response": conv_lib.build_conversation(conv_id, index)}
    except Exception as exc:
        logging.error(f"get_conversation failed: {exc}")
        return {"error": True, "response": str(exc)}
