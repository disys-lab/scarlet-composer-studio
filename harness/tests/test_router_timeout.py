"""
Unit tests for on_key()'s timeout/on_timeout parameters and the
double-fire prevention between a real message and a same-key timeout - no
Redis, no subprocess, same FakeBus pattern as test_router.py.
"""
import threading
import time

from tests.test_router import FakeBus, _key_by_id
from scarlet_agentic_harness.router import MessageRouter


def test_on_timeout_fires_if_nothing_arrives_in_time():
    bus = FakeBus()
    router = MessageRouter(bus, key_fn=_key_by_id, poll_timeout=0.05)
    try:
        timed_out = threading.Event()
        router.on_key("req-1", lambda msg: None, timeout=0.3, on_timeout=timed_out.set)
        assert timed_out.wait(timeout=2)
    finally:
        router.stop()


def test_on_timeout_does_not_fire_if_the_real_message_arrives_first():
    bus = FakeBus()
    router = MessageRouter(bus, key_fn=_key_by_id, poll_timeout=0.05)
    try:
        received = []
        timed_out = threading.Event()
        got_callback = threading.Event()

        def callback(msg):
            received.append(msg)
            got_callback.set()

        router.on_key("req-1", callback, timeout=2.0, on_timeout=timed_out.set)
        bus.push({"id": "req-1", "body": "arrived in time"})

        assert got_callback.wait(timeout=2)
        assert received == [{"id": "req-1", "body": "arrived in time"}]
        # Give a scheduled (but should-be-cancelled) timeout a chance to
        # misfire if the cancellation didn't actually work.
        assert not timed_out.wait(timeout=1)
    finally:
        router.stop()


def test_real_callback_does_not_fire_after_its_own_timeout_already_fired():
    bus = FakeBus()
    router = MessageRouter(bus, key_fn=_key_by_id, poll_timeout=0.05)
    try:
        received = []
        timed_out = threading.Event()
        router.on_key("req-1", lambda msg: received.append(msg), timeout=0.3, on_timeout=timed_out.set)

        assert timed_out.wait(timeout=2)
        # A late arrival after the timeout already gave up must be a no-op,
        # not a delayed invocation of the original callback.
        bus.push({"id": "req-1", "body": "too late"})
        time.sleep(0.5)
        assert received == []
    finally:
        router.stop()


def test_forget_cancels_a_scheduled_timeout_too():
    bus = FakeBus()
    router = MessageRouter(bus, key_fn=_key_by_id, poll_timeout=0.05)
    try:
        timed_out = threading.Event()
        router.on_key("req-1", lambda msg: None, timeout=0.3, on_timeout=timed_out.set)
        router.forget("req-1")
        assert not timed_out.wait(timeout=1)
    finally:
        router.stop()


def test_timeout_scan_interval_bounds_how_fast_a_short_deadline_actually_fires():
    """
    Found via a real-LLM end-to-end test (see README / conversation
    history): a deadline shorter than the watcher's own scan interval
    doesn't fire any sooner than the next scan - the deadline value alone
    isn't the whole story. This proves timeout_scan_interval is actually
    threaded through to TimeoutWatcher, by observing a *fast* scan
    interval let a very short deadline fire promptly.
    """
    bus = FakeBus()
    router = MessageRouter(bus, key_fn=_key_by_id, poll_timeout=0.05, timeout_scan_interval=0.02)
    try:
        timed_out = threading.Event()
        started = time.time()
        router.on_key("req-1", lambda msg: None, timeout=0.01, on_timeout=timed_out.set)
        assert timed_out.wait(timeout=1)
        elapsed = time.time() - started
        # Generous bound (not a race against the exact 0.02s scan interval)
        # - just proving this is nowhere near the OLD hardcoded 0.5s default.
        assert elapsed < 0.3, f"took {elapsed:.2f}s - timeout_scan_interval doesn't seem to be taking effect"
    finally:
        router.stop()
