"""
Shared, cached Messenger instances - one per bus name, reused across
requests.

Found by actually running this against real Redis: Messenger.__init__
(scarlets/messaging/Messenger.py) unconditionally calls Register() (writes
a real registry entry for itself), starts a background heartbeat thread,
and calls register_scarlet_definition() for the bus - real, deliberate
side effects for a real agent process, but not something a read-only API
endpoint should trigger fresh on every single request. Constructing a new
Messenger per request (which routers/agents.py and routers/dashboard.py
did in their first draft) leaked one perpetual heartbeat thread per
request and made composer-api itself show up as a phantom "agent" in its
own GatherStatus() results.

get_messenger(bus) constructs at most one Messenger per bus name for this
process's lifetime. AGENT_ID is a value real agents can never collide
with (their own agentId is always f"{APP_ID}_{NODE_ADDRESS}"), so
filtering it out of GatherStatus() results is unambiguous - see
routers/agents.py / routers/dashboard.py.
"""
from scarlets.messaging import Messenger

AGENT_ID = "__composer_api__"

_messengers: dict[str, Messenger] = {}


def get_messenger(bus: str) -> Messenger:
    if bus not in _messengers:
        _messengers[bus] = Messenger(bus, agentId=AGENT_ID)
    return _messengers[bus]


def known_buses() -> set[str]:
    """Buses composer-api itself has constructed a Messenger for - used to
    exclude the scarlet_definition_{bus} entries that construction itself
    creates as a side effect from the dashboard's scarlet-definition count,
    so composer-api's own read traffic doesn't inflate that stat."""
    return set(_messengers.keys())
