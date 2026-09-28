"""
Shared, cached Messenger/Mapper instances - one per scarlet name, reused
across requests.

Found by actually running this against real Redis: Messenger.__init__
(scarlets/messaging/Messenger.py) unconditionally calls Register() (writes
a real registry entry for itself), starts a background heartbeat thread,
and calls register_scarlet_definition() for the bus - real, deliberate
side effects for a real agent process, but not something a read-only API
endpoint should trigger fresh on every single request. Constructing a new
Messenger per request (which routers/agents.py and routers/dashboard.py
did in their first draft) leaked one perpetual heartbeat thread per
request and made composer-api itself show up as a phantom "agent" in its
own GatherStatus() results. Mapper.__init__ (scarlets/core/Mapper.py)
self-registers the same way, so the same caching applies to it.

get_messenger(bus)/get_mapper(name) construct at most one instance per
name for this process's lifetime. AGENT_ID is a value real agents can
never collide with (their own agentId is always f"{APP_ID}_{NODE_ADDRESS}"),
so filtering it out of GatherStatus() results is unambiguous - see
routers/agents.py / routers/dashboard.py.

─── Why bus_exists() gates get_messenger ──────────────────────────────────

Caching bounds how many instances get built, but not *which* names they
get built for. The bus name on /api/agents is a query parameter, so any
string a caller sends becomes a scarlet: the Agents page used to re-query
on every keystroke, and typing "scarlet" left seven permanent
scarlet_definition_* entries behind - s, sc, sca, scar... - each with its
own heartbeat thread, none of which anything ever cleans up. The UI now
only queries on an explicit Save, but a saved typo would still do it once.

bus_exists() makes that impossible rather than unlikely: a name with no
scarlet_definition_ entry is one nobody has ever created, so there is
nothing to read and no reason to build anything. Callers treat False as
"no data", not as an error.

The guard also makes composer-api's own register_scarlet_definition() call
inert for buses, which is the real fix: that function early-returns when
the key already exists (overwrite=False, ScarletUtils.py), and after this
gate every bus name reaching Messenger() is one whose key exists - so
composer-api can no longer bring a bus into being by being asked about it.
Register() still runs for real buses, which is intended: a viewer is a
genuine participant on a bus it is actually watching.

Checking the definition key rather than the agent registry is deliberate
*for buses*: Messenger's definitions are written with no TTL (Messenger.py
passes no expiry to register_scarlet_definition), so a real bus whose
agents have all stopped still resolves - only a name nobody ever used
comes back missing.

─── Why get_mapper is NOT gated the same way ──────────────────────────────

Two reasons, and the second one is a trap worth spelling out.

First, there is no untrusted input to guard against: mapper names are
never typed by a user. They are read back out of agent status records
(each agent publishes its own activity_mapper - see the harness's
__main__.py), so a name only reaches get_mapper because a live agent
said it is using it. That is a stronger existence signal than any key
lookup.

Second, the definition key would be the *wrong* signal here anyway.
Mapper.__init__ passes expiry=scarletDataExpiry (3600s by default,
scarlets/types/ScarletBase.py) to register_scarlet_definition, and only
ever writes it at construction - nothing refreshes it. So a worker that
has been up for more than an hour still has a live mapper, still
publishing activity, whose scarlet_definition_ key expired long ago.
Gating on it would make the Activity panel go blank after an hour on
exactly the healthy deployments it is meant to show.
"""
from scarlets.core.Mapper import Mapper
from scarlets.messaging import Messenger
from scarlets.utils.ScarletUtils import redisConnect

AGENT_ID = "__composer_api__"

_messengers: dict[str, Messenger] = {}
_mappers: dict[str, Mapper] = {}


def bus_exists(bus: str) -> bool:
    """
    Whether `bus` is a Messenger bus anything has ever created.

    Parameters
    ----------
    bus : str
        A Messenger bus name, typically straight off a query parameter.

    Returns
    -------
    bool
        `True` if ``scarlet_definition_{bus}`` is present in Redis.
        `False` for an empty/whitespace name, a name nobody has created,
        or if Redis itself is unreachable - callers treat all three the
        same way, as "nothing to read", so a transient Redis failure
        degrades to an empty result rather than to creating a scarlet.
    """
    if not bus or not bus.strip():
        return False
    try:
        r = redisConnect(decode_responses=True)
        return bool(r.exists(f"scarlet_definition_{bus}"))
    except Exception:
        return False


def get_messenger(bus: str) -> Messenger:
    """Cached Messenger for `bus`. Gate on `bus_exists` first."""
    if bus not in _messengers:
        _messengers[bus] = Messenger(bus, agentId=AGENT_ID)
    return _messengers[bus]


def get_mapper(name: str) -> Mapper:
    """
    Cached Mapper for `name`.

    Deliberately ungated - see this module's docstring for why the
    definition-key check that guards `get_messenger` would be both
    unnecessary and actively wrong here.
    """
    if name not in _mappers:
        _mappers[name] = Mapper(name)
    return _mappers[name]
