"""
MessageRouter — the single owner of Receive() for one Messenger bus.

scarlets' Messenger is a strict per-agent FIFO (see the installed package's
Messenger._pollInbox: a head/tail sequence-number pair per agentId, with an
unconditional ack on read - no peek, no filtering, no "put it back if it's
not mine"). That is fine as long as exactly one logical waiter calls
Receive() for the whole lifetime of a request, which was true everywhere in
this codebase until now: worker.poll_once() and Skill.coordinate() were
always the only caller of a given bus's Receive() in flight at a time.

It stops being safe the moment two skill invocations are in flight on the
same agent/bus concurrently - which is exactly what worker-level concurrency
(handling more than one dispatch at a time) requires. If invocation A's
coordinate() and invocation B's coordinate() (or contribute()) both call
Receive() independently, whichever call happens to run at the right moment
dequeues - and irreversibly consumes - a message meant for the other, since
the ack happens on read regardless of who was asking or what they expected.
That is a silent, hard-to-reproduce message-loss bug waiting to happen, not
a theoretical concern - it is the direct reason this module exists instead
of just spawning a thread per dispatch message.

MessageRouter fixes this by making exactly one background thread the sole
caller of a bus's Receive(), and demultiplexing each message in-process to
per-key queues (key is normally a request_id) that callers poll instead of
touching the bus directly. Keys are auto-vivified on first sight from
either side (a waiter calling receive_for() before the message arrives, or
the poller seeing the message before anyone asks for it) - order between
those two never matters, so no message that carries a recognized key is
ever dropped for arriving "too early". Messages the key function decides
aren't request-scoped (skill_contribute/skill_coordinate dispatches, which
are unsolicited from the receiving agent's point of view - see key_fn
callers in buses.py) go to `default_handler` instead, which is how worker
dispatch now flows: through the same router that services request-scoped
waits, not a second independent Receive() loop.
"""
import queue
import threading
from typing import Callable


class MessageRouter:
    def __init__(
        self,
        bus,
        key_fn: Callable[[dict], object | None],
        default_handler: Callable[[dict], None] | None = None,
        poll_timeout: float = 1.0,
    ):
        """
        bus: a Messenger instance - becomes the *only* thing calling
          bus.Receive() from this point on. Nothing else may call
          bus.Receive() directly without racing this router's poller.
        key_fn: msg -> key or None. None means "not request-scoped", always
          routed to default_handler regardless of whether any queue exists.
        default_handler: mutable, may be set/replaced after construction
          (worker.py's entrypoint sets this once it knows how to dispatch
          skill invocations - Buses itself has no opinion on dispatch).
        """
        self._bus = bus
        self._key_fn = key_fn
        self.default_handler = default_handler
        self._poll_timeout = poll_timeout
        self._queues: dict[object, queue.Queue] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def receive_for(self, key, timeout: float) -> dict | None:
        """
        One-shot poll for the next message matching `key`, mirroring
        Messenger.Receive(timeout=...)'s contract exactly (None on timeout)
        so call sites keep their existing polling-loop shape - only the
        object they call it on changes.
        """
        q = self._queue_for(key)
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            return None

    def forget(self, key) -> None:
        """
        Drop the queue for `key`. Call once a request is fully done (success
        or error) - keys are UUIDs minted per request, so without this the
        router leaks one queue per request for the lifetime of the process.
        """
        with self._lock:
            self._queues.pop(key, None)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _queue_for(self, key) -> queue.Queue:
        with self._lock:
            q = self._queues.get(key)
            if q is None:
                q = self._queues[key] = queue.Queue()
            return q

    def _run(self) -> None:
        while not self._stop.is_set():
            msg = self._bus.Receive(timeout=self._poll_timeout)
            if not msg:
                continue
            key = self._key_fn(msg)
            if key is not None:
                self._queue_for(key).put(msg)
            elif self.default_handler is not None:
                self.default_handler(msg)
            # else: not request-scoped and nothing registered to handle
            # unsolicited messages - dropped, matching today's behavior for
            # any message nobody expects (e.g. the head's global bus, which
            # never wants unsolicited dispatch messages).
