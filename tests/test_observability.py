"""
Real Redis test of observability.py + CancellationRegistry's optional
activity publishing - Mapper is Redis-backed, so unlike cancellation.py's
own unit tests, this can't be faked in-process.

Two separate CancellationRegistry instances (standing in for two different
worker processes) publish to the *same* shared Mapper name (by app_id, per
observability.activity_mapper()), proving snapshot() gives a real
cross-agent view, not just "read back your own writes."
"""
import os

from scarlet_agentic_harness import observability
from scarlet_agentic_harness.cancellation import CancellationRegistry
from tests.helpers import APP_ID


def _setup_env(redis_conn_info) -> None:
    os.environ.update({
        "REDIS_HOST": redis_conn_info["host"],
        "REDIS_PORT": redis_conn_info["port"],
        "REDIS_AUTH_TOKEN": redis_conn_info["auth_token"],
        "APP_ID": APP_ID,
        "NODE_ADDRESS": "observability-test",
    })


def test_registry_publishes_in_flight_requests_and_snapshot_reads_it_back(redis_conn_info):
    _setup_env(redis_conn_info)
    mapper = observability.activity_mapper(APP_ID)
    registry = CancellationRegistry(activity_mapper=mapper, agent_id=f"{APP_ID}_worker-a")

    try:
        registry.create("req-1")
        registry.create("req-2")

        snap = observability.snapshot(mapper)
        assert f"{APP_ID}_worker-a" in snap
        published = snap[f"{APP_ID}_worker-a"]
        assert sorted(published["in_flight"]) == ["req-1", "req-2"]
        assert published["count"] == 2

        registry.forget("req-1")
        snap = observability.snapshot(mapper)
        published = snap[f"{APP_ID}_worker-a"]
        assert published["in_flight"] == ["req-2"]
        assert published["count"] == 1
    finally:
        mapper.clearAll()


def test_snapshot_shows_multiple_agents_publishing_to_the_shared_mapper(redis_conn_info):
    _setup_env(redis_conn_info)
    mapper = observability.activity_mapper(APP_ID)
    registry_a = CancellationRegistry(activity_mapper=mapper, agent_id=f"{APP_ID}_worker-a")
    registry_b = CancellationRegistry(activity_mapper=mapper, agent_id=f"{APP_ID}_worker-b")

    try:
        registry_a.create("req-from-a")
        registry_b.create("req-from-b-1")
        registry_b.create("req-from-b-2")

        snap = observability.snapshot(mapper)
        assert snap[f"{APP_ID}_worker-a"]["in_flight"] == ["req-from-a"]
        assert sorted(snap[f"{APP_ID}_worker-b"]["in_flight"]) == ["req-from-b-1", "req-from-b-2"]
    finally:
        mapper.clearAll()


def test_registry_without_activity_mapper_does_not_touch_redis(redis_conn_info):
    _setup_env(redis_conn_info)
    # No activity_mapper given - create()/forget() must not raise or block
    # trying to publish, and there's nothing to read back.
    registry = CancellationRegistry()
    registry.create("req-1")
    registry.forget("req-1")
    assert registry.snapshot() == []
