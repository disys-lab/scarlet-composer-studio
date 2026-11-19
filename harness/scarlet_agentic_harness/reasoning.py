"""
Publish the head's own reasoning onto the bus, so something other than the
head process can see it.

`head.converse` already emits a structured event for every step it takes -
narration, each tool call, each dispatch, each tool result, the final
answer (see its `on_event` parameter). Those events were only ever handed
to a local callback: `mcp_server.py` printed them to stderr, `__main__.py`
logged them. Useful while attached to one container, invisible to anything
else, and gone as soon as the process moved on.

The messages agents exchange *are* on the bus and can be read back, but
they only show the outside of a decision - that the head dispatched `sum`,
that a worker replied. Why it chose `sum` twice, what it made of the
results, what it concluded, is a direct HTTPS exchange with the model that
touches Redis nowhere. Publishing these events is what turns a sequence of
messages into an explanation.

Addressed to a reserved agent id on the head bus rather than a bus of its
own. `Messenger.Send` writes into the recipient's inbox without requiring
that recipient to exist, so this needs no new scarlet and no registration -
the reserved id never appears in `GatherStatus`, because only constructing
a `Messenger` registers anything. It also means a conversation's reasoning
expires exactly when the bus that carried it does, rather than acquiring a
separate lifetime.

Opt-out rather than opt-in (`PUBLISH_REASONING=false`). The events carry
model output and real tool results, so anyone who can read Redis can read
them - fine for a tutorial fleet, worth a thought for one handling real
data. But a trace you have to remember to switch on beforehand is never on
when you need it, which is the failure this exists to prevent.
"""
import os
from scarlet_agentic_harness.publishing_event_handler import PublishingEventHandler

from scarlets.utils.RedisLogger import RedisLogger

# Reserved recipient. Double-underscored so it cannot collide with a real
# agent id, which is always f"{APP_ID}_{NODE_ADDRESS}".
REASONING_SINK = "__head_reasoning__"

MSG_TYPE = "head_reasoning"


def publishing_enabled() -> bool:
    """Whether reasoning should be published. `PUBLISH_REASONING=false` disables it."""
    return os.environ.get("PUBLISH_REASONING", "true").strip().lower() != "false"


def publishing_on_event(buses, inner=None):
    """
    Wrap a `converse` `on_event` callback so its events also reach the bus.

    Parameters
    ----------
    buses : Buses
        The agent's buses. Events go to the global bus, addressed to
        `REASONING_SINK`.
    inner : callable or None, optional
        The caller's existing handler, invoked first and unchanged - this
        adds a destination rather than replacing one.

    Returns
    -------
    callable
        A drop-in `on_event`. Publishing failures are logged and
        swallowed: this is observability on the head's critical path, and
        it must never be able to break the conversation it describes.
    """
    return PublishingEventHandler(buses, REASONING_SINK, MSG_TYPE,
                                  publishing_enabled(), inner)
