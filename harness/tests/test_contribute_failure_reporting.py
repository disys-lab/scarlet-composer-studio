"""
A skill that raises must tell the head, not vanish.

contribute() and coordinate() run on a thread whose only exception handling
is a `finally`, so anything they raised used to kill that thread silently:
no readiness signal, no skill_result, nothing. The head then waited out its
full timeout, retried onto the same broken worker, failed identically, and
gave up - with the only account of the real cause being a traceback on the
container's stderr, which the Composer's log view cannot show.

The case that produced this: CSV_PATH naming a file that did not exist, so
local_numbers() raised FileNotFoundError inside contribute(). These tests
reproduce that shape directly rather than mocking an abstract failure.
"""
import pytest

from scarlet_agentic_harness import worker as worker_mod
from scarlet_agentic_harness.cancellation import CancellationToken
from scarlet_agentic_harness.skills.base import Skill


class _RecordingBus:
    def __init__(self):
        self.sent = []

    def Send(self, target, message):
        self.sent.append((target, message))


class _Buses:
    def __init__(self):
        self.global_bus = _RecordingBus()
        self.local_bus = _RecordingBus()


class _Config:
    agent_id = "app_worker1"
    role = "worker"


class _FailingContribute(Skill):
    name = "sum"
    description = "raises the way a missing CSV_PATH does"

    def contribute(self, ctx, request):
        raise FileNotFoundError("[Errno 2] No such file or directory: '/data/worker1.csv'")

    def coordinate(self, ctx, request, workers):
        raise AssertionError("coordinate must not run after contribute raised")


class _FailingCoordinate(Skill):
    name = "sum"
    description = "contributes fine, then falls over coordinating"

    def contribute(self, ctx, request):
        return None

    def coordinate(self, ctx, request, workers):
        raise RuntimeError("federator exploded")


def _dispatch(skill, msg_type):
    buses = _Buses()
    msg = {
        "from": "app_head",
        "body": {
            "type": msg_type, "skill": "sum", "request_id": "req-1",
            "coordinator": "app_worker1", "workers": ["app_worker1"],
        },
    }
    with pytest.raises(Exception):
        # Re-raised on purpose so the traceback still reaches stderr; the
        # point of these tests is what got *sent* before that.
        worker_mod.handle_message(
            msg, _Config(), buses, {"sum": skill}, CancellationToken(),
        )
    return buses


def test_contribute_failure_is_reported_to_the_head():
    buses = _dispatch(_FailingContribute(), "skill_coordinate")

    assert len(buses.global_bus.sent) == 1, "the head must be told exactly once"
    target, body = buses.global_bus.sent[0]
    assert target == "app_head"
    assert body["type"] == "skill_result"
    assert body["request_id"] == "req-1"
    assert body["status"] == "error"

    # The reason has to name the real cause. A message saying only
    # "coordinator did not respond in time" is what this replaces, and it
    # sent people looking in entirely the wrong place.
    assert "FileNotFoundError" in body["detail"]
    assert "/data/worker1.csv" in body["detail"]
    assert "app_worker1" in body["detail"]
    assert "contribute" in body["detail"]


def test_a_broken_worker_is_not_retried():
    """
    retryable=False, because a second attempt against the same worker cannot
    fix an unreadable data source - and retrying is exactly the storm this
    replaces: the same failure re-run until max_attempts, minutes spent, and
    a final error naming a timeout rather than the cause.
    """
    buses = _dispatch(_FailingContribute(), "skill_coordinate")
    _, body = buses.global_bus.sent[0]
    assert body["retryable"] is False


def test_a_failing_contributor_reports_too():
    """A non-coordinator matters just as much: the coordinator is waiting."""
    buses = _dispatch(_FailingContribute(), "skill_contribute")
    assert len(buses.global_bus.sent) == 1
    _, body = buses.global_bus.sent[0]
    assert body["status"] == "error"
    assert "FileNotFoundError" in body["detail"]


def test_coordinate_failure_is_reported_too():
    """Same hole on the other side - a coordinator that raises also left the head waiting."""
    buses = _dispatch(_FailingCoordinate(), "skill_coordinate")
    assert len(buses.global_bus.sent) == 1
    _, body = buses.global_bus.sent[0]
    assert body["status"] == "error"
    assert "RuntimeError" in body["detail"]
    assert "coordinate" in body["detail"]


def test_a_working_skill_is_unaffected():
    """The success path must be untouched - one skill_result, carrying the result."""
    class _Fine(Skill):
        name = "sum"
        description = "works"

        def contribute(self, ctx, request):
            return None

        def coordinate(self, ctx, request, workers):
            return {"status": "ok", "result": 42, "n": 7}

    buses = _Buses()
    worker_mod.handle_message(
        {"from": "app_head", "body": {"type": "skill_coordinate", "skill": "sum",
                                      "request_id": "req-2", "workers": []}},
        _Config(), buses, {"sum": _Fine()}, CancellationToken(),
    )
    assert len(buses.global_bus.sent) == 1
    _, body = buses.global_bus.sent[0]
    assert body["status"] == "ok" and body["result"] == 42
    assert "retryable" not in body
