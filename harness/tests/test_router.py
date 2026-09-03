"""
Unit tests for MessageRouter - no Redis, no subprocess. A FakeBus stands in
for a real Messenger: all MessageRouter ever needs from a bus is
Receive(timeout) -> dict|None, so a plain in-memory queue is a faithful
substitute for testing the router's own demultiplexing logic in isolation.

Covers on_key() specifically (router.py's new non-blocking registration,
the piece head.run_skill()'s async form will build on) alongside the
existing receive_for()/default_handler paths, to make sure the two
delivery modes coexist correctly on the same router.
"""
import queue
import threading
import time

from scarlet_agentic_harness.router import MessageRouter


class FakeBus:
    """Stands in for a real Messenger - Receive(timeout) is the entire
    surface MessageRouter needs."""

    def __init__(self):
        self._q: queue.Queue = queue.Queue()

    def push(self, msg: dict) -> None:
        self._q.put(msg)

    def Receive(self, timeout: float = 0):
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None


def _key_by_id(msg: dict):
    return msg.get("id")


def test_on_key_fires_for_a_message_that_arrives_after_registration():
    bus = FakeBus()
    router = MessageRouter(bus, key_fn=_key_by_id, poll_timeout=0.05)
    try:
        received = []
        done = threading.Event()

        def callback(msg):
            received.append(msg)
            done.set()

        router.on_key("req-1", callback)
        bus.push({"id": "req-1", "body": "hello"})

        assert done.wait(timeout=2)
        assert received == [{"id": "req-1", "body": "hello"}]
    finally:
        router.stop()


def test_on_key_fires_immediately_for_a_message_that_already_arrived():
    bus = FakeBus()
    router = MessageRouter(bus, key_fn=_key_by_id, poll_timeout=0.05)
    try:
        # Push before anyone registers interest - the router's own thread
        # will queue it under "req-1" with no callback waiting yet.
        bus.push({"id": "req-1", "body": "early"})
        time.sleep(0.2)  # let the router's poller pick it up and queue it

        received = []
        done = threading.Event()

        def callback(msg):
            received.append(msg)
            done.set()

        router.on_key("req-1", callback)

        assert done.wait(timeout=2)
        assert received == [{"id": "req-1", "body": "early"}]
    finally:
        router.stop()


def test_on_key_callback_runs_on_a_different_thread_than_the_caller():
    bus = FakeBus()
    router = MessageRouter(bus, key_fn=_key_by_id, poll_timeout=0.05)
    try:
        caller_thread = threading.current_thread().ident
        callback_thread = []
        done = threading.Event()

        def callback(msg):
            callback_thread.append(threading.current_thread().ident)
            done.set()

        router.on_key("req-1", callback)
        bus.push({"id": "req-1"})

        assert done.wait(timeout=2)
        assert callback_thread[0] != caller_thread
    finally:
        router.stop()


def test_on_key_registration_returns_immediately_without_blocking():
    bus = FakeBus()
    router = MessageRouter(bus, key_fn=_key_by_id, poll_timeout=0.05)
    try:
        start = time.time()
        router.on_key("req-never-arrives", lambda msg: None)
        elapsed = time.time() - start
        assert elapsed < 0.1  # no message ever arrives - on_key must not wait for one
    finally:
        router.stop()


def test_forget_prevents_a_registered_callback_from_firing():
    bus = FakeBus()
    router = MessageRouter(bus, key_fn=_key_by_id, poll_timeout=0.05)
    try:
        fired = threading.Event()
        router.on_key("req-1", lambda msg: fired.set())
        router.forget("req-1")
        bus.push({"id": "req-1"})

        assert not fired.wait(timeout=1)
    finally:
        router.stop()


def test_default_handler_still_used_for_unkeyed_messages():
    bus = FakeBus()
    handled = []
    done = threading.Event()

    def default_handler(msg):
        handled.append(msg)
        done.set()

    def key_fn(msg):
        return msg.get("id")  # None for messages with no "id"

    router = MessageRouter(bus, key_fn=key_fn, default_handler=default_handler, poll_timeout=0.05)
    try:
        bus.push({"body": "unsolicited, no id"})
        assert done.wait(timeout=2)
        assert handled == [{"body": "unsolicited, no id"}]
    finally:
        router.stop()


def test_receive_for_still_works_unchanged_alongside_on_key():
    bus = FakeBus()
    router = MessageRouter(bus, key_fn=_key_by_id, poll_timeout=0.05)
    try:
        bus.push({"id": "req-1", "body": "for receive_for"})
        msg = router.receive_for("req-1", timeout=2)
        assert msg == {"id": "req-1", "body": "for receive_for"}
    finally:
        router.stop()
