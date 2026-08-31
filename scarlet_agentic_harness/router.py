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

on_key() is the non-blocking counterpart to receive_for(): register a
callback for a key and return immediately, instead of blocking a thread
until a match or timeout. The callback fires on a freshly spawned thread
(never the router's own polling thread - handing off is exactly the same
discipline worker.start_dispatch() already follows for default_handler,
and for the same reason: the polling thread must never do slow work, or it
stalls delivery to every other key on this bus). One-shot per
registration - call on_key() again inside the callback to keep watching.
This is what lets a caller wait for a reply without occupying a thread for
the whole wait: head.run_skill()'s async form registers a callback and
returns, rather than blocking in _wait_for_result().

on_key() also takes an optional timeout/on_timeout pair, backed by
TimeoutWatcher (timeout_watcher.py) - a single shared scanning thread per
router, not one thread per pending wait. This router owns the double-fire
prevention TimeoutWatcher itself knows nothing about: when the real
message arrives, any scheduled timeout for that key is cancelled before
the real callback fires; when a timeout fires instead, the real callback
registration is dropped first, so a late-arriving message afterward is
silently ignored rather than invoking a callback that already gave up.
"""
import queue
import threading
import time
from typing import Callable

from scarlet_agentic_harness.timeout_watcher import TimeoutWatcher


class MessageRouter:
    def __init__(
        self,
        bus,
        key_fn: Callable[[dict], object | None],
        default_handler: Callable[[dict], None] | None = None,
        poll_timeout: float = 1.0,
        timeout_scan_interval: float = 0.5,
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
        timeout_scan_interval: passed straight to TimeoutWatcher - see its
          docstring. Previously hardcoded (TimeoutWatcher's own 0.5s
          default, unreachable from here at all) - found to matter in
          practice while forcing a real end-to-end deliberation test: a
          deadline shorter than this scan interval doesn't fire any
          sooner, it just waits for the next scan. Exposed here, and
          threaded from Buses/HarnessConfig, instead of only reachable by
          poking a router's private _watcher attribute.
        """
        self._bus = bus
        self._key_fn = key_fn
        self.default_handler = default_handler
        self._poll_timeout = poll_timeout
        self._queues: dict[object, queue.Queue] = {}
        self._callbacks: dict[object, Callable[[dict], None]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._watcher = TimeoutWatcher(scan_interval=timeout_scan_interval)
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

    def on_key(
        self,
        key,
        callback: Callable[[dict], None],
        timeout: float | None = None,
        on_timeout: Callable[[], None] | None = None,
    ) -> None:
        """
        Register callback to fire, on a new thread, the next time a message
        matching key arrives. Non-blocking - registers and returns.

        If a message matching key already arrived and is sitting unclaimed
        in key's queue (e.g. from before this registration - the same
        "doesn't matter which came first" guarantee receive_for() gets),
        the oldest one is drained and the callback fires with it right
        away, still on a new thread rather than the caller's - and no
        timeout is scheduled in that case, since the wait is already over.

        timeout/on_timeout: if given, on_timeout fires (on a new thread) if
        no matching message arrives within `timeout` seconds. Mutually
        exclusive with callback ever firing for this registration - see
        the module docstring's double-fire prevention.
        """
        pending = None
        with self._lock:
            q = self._queues.get(key)
            if q is not None and not q.empty():
                pending = q.get_nowait()
            else:
                self._callbacks[key] = callback
        if pending is not None:
            threading.Thread(target=callback, args=(pending,), daemon=True).start()
            return
        if timeout is not None:
            self._watcher.schedule(key, time.time() + timeout, self._make_timeout_handler(key, on_timeout))

    def forget(self, key) -> None:
        """
        Drop the queue and any pending callback for `key`, and cancel any
        scheduled timeout for it. Call once a request is fully done
        (success or error) - keys are UUIDs minted per request, so without
        this the router leaks one queue (and possibly one never-fired
        callback or timeout) per request for the lifetime of the process.
        """
        with self._lock:
            self._queues.pop(key, None)
            self._callbacks.pop(key, None)
        self._watcher.cancel(key)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._watcher.stop()

    def _make_timeout_handler(self, key, on_timeout: Callable[[], None] | None) -> Callable[[], None]:
        def _handler():
            # Whoever successfully pops the callback under the lock is the
            # one that actually happened - the real message and a
            # same-moment timeout race here, and only the winner acts. If
            # _run() already popped it (the real message won), this pop
            # returns None and on_timeout must NOT fire - the wait was
            # already satisfied for a real reason.
            with self._lock:
                had_callback = self._callbacks.pop(key, None) is not None
            if had_callback and on_timeout is not None:
                on_timeout()
        return _handler

    def _queue_for(self, key) -> queue.Queue:
        with self._lock:
            return self._queue_for_locked(key)

    def _queue_for_locked(self, key) -> queue.Queue:
        # Caller must already hold self._lock.
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
            if key is None:
                if self.default_handler is not None:
                    self.default_handler(msg)
                # else: not request-scoped and nothing registered to handle
                # unsolicited messages - dropped, matching today's behavior
                # for any message nobody expects.
                continue
            callback = None
            with self._lock:
                callback = self._callbacks.pop(key, None)
                if callback is None:
                    self._queue_for_locked(key).put(msg)
            if callback is not None:
                self._watcher.cancel(key)  # real message won - no timeout should fire for this key
                threading.Thread(target=callback, args=(msg,), daemon=True).start()
