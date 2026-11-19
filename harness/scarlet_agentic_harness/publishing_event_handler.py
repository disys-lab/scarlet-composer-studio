"""An on_event handler that also publishes the head's reasoning to the bus."""
from scarlets.utils.RedisLogger import RedisLogger


class PublishingEventHandler:
    """
    Forwards `converse` events to an inner handler and to the reasoning sink.

    Adds a destination rather than replacing one: `inner` is called first
    and unchanged. Publishing failures are logged and swallowed - this is
    observability on the head's critical path and must never be able to
    break the conversation it describes.

    Parameters
    ----------
    buses : Buses
        Events go to the global bus, addressed to `sink`.
    sink : str
        Agent id that collects reasoning events.
    msg_type : str
        Wire discriminator stamped on every published event.
    enabled : bool
        Resolved once at construction, so toggling it mid-conversation
        cannot change behaviour halfway through.
    inner : callable or None, optional
        The caller's existing handler.
    """

    def __init__(self, buses, sink: str, msg_type: str, enabled: bool,
                 inner=None):
        self._buses = buses
        self._sink = sink
        self._msg_type = msg_type
        self._enabled = enabled
        self._inner = inner

    def __call__(self, event: dict) -> None:
        """Pass `event` to the inner handler, then publish it."""
        if self._inner is not None:
            self._inner(event)
        if not self._enabled:
            return
        try:
            # Spread first, then set "type". The other way round lets the
            # event's own type ("narration", "tool_call", ...) overwrite the
            # wire discriminator, and every message would go out labelled as
            # whatever step produced it - indistinguishable from ordinary bus
            # traffic. The event's own type is kept under "event".
            #
            # conv_id already rides on every event: converse stamps it,
            # because it mints the value and no caller knows it up front.
            self._buses.global_bus.Send(self._sink, {
                **event,
                "event": event.get("type"),
                "type": self._msg_type,
            })
        except Exception as exc:
            RedisLogger.warning(
                f"reasoning publish failed ({event.get('type')}): {exc}")
