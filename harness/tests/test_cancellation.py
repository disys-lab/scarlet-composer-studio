"""
Unit tests for CancellationToken/CancellationRegistry - no Redis, no
subprocess, pure in-process logic.
"""
import threading
import time

from scarlet_agentic_harness.cancellation import CancellationRegistry, CancellationToken, describe_in_flight


def test_token_starts_uncancelled():
    token = CancellationToken()
    assert not token.event.is_set()


def test_cancel_sets_the_event():
    token = CancellationToken()
    token.cancel()
    assert token.event.is_set()


def test_on_cancel_fires_when_cancel_is_called_after_registration():
    token = CancellationToken()
    fired = threading.Event()
    token.on_cancel(fired.set)
    assert not fired.is_set()
    token.cancel()
    assert fired.wait(timeout=1)


def test_on_cancel_fires_immediately_if_already_cancelled():
    token = CancellationToken()
    token.cancel()
    fired = threading.Event()
    token.on_cancel(fired.set)  # registered *after* cancel() already ran
    assert fired.wait(timeout=1)


def test_on_cancel_callback_runs_on_a_different_thread():
    token = CancellationToken()
    caller_thread = threading.current_thread().ident
    callback_thread = []
    done = threading.Event()

    def callback():
        callback_thread.append(threading.current_thread().ident)
        done.set()

    token.on_cancel(callback)
    token.cancel()
    assert done.wait(timeout=1)
    assert callback_thread[0] != caller_thread


def test_cancel_is_idempotent_callbacks_run_once():
    token = CancellationToken()
    calls = []
    token.on_cancel(lambda: calls.append(1))
    token.cancel()
    token.cancel()
    token.cancel()
    import time
    time.sleep(0.1)
    assert calls == [1]


def test_multiple_callbacks_all_fire():
    token = CancellationToken()
    fired = []
    lock = threading.Lock()
    done = threading.Event()

    def make_cb(n):
        def cb():
            with lock:
                fired.append(n)
                if len(fired) == 3:
                    done.set()
        return cb

    token.on_cancel(make_cb(1))
    token.on_cancel(make_cb(2))
    token.on_cancel(make_cb(3))
    token.cancel()

    assert done.wait(timeout=1)
    assert sorted(fired) == [1, 2, 3]


def test_registry_create_and_cancel():
    registry = CancellationRegistry()
    token = registry.create("req-1")
    registry.cancel("req-1")
    assert token.event.is_set()


def test_registry_cancel_on_unknown_request_id_is_a_noop():
    registry = CancellationRegistry()
    registry.cancel("does-not-exist")  # must not raise


def test_registry_forget_removes_the_token():
    registry = CancellationRegistry()
    token = registry.create("req-1")
    registry.forget("req-1")
    registry.cancel("req-1")  # no longer tracked - must not reach the original token
    assert not token.event.is_set()


def test_token_tracks_skill_name_and_progress():
    token = CancellationToken(skill_name="median")
    assert token.skill_name == "median"
    assert token.progress_snapshot() == {}
    token.update_progress(ready_count=1, expected_count=3)
    assert token.progress_snapshot() == {"ready_count": 1, "expected_count": 3}
    token.update_progress(ready_count=2)  # partial update - expected_count untouched
    assert token.progress_snapshot() == {"ready_count": 2, "expected_count": 3}


def test_registry_snapshot_reports_skill_elapsed_and_progress():
    registry = CancellationRegistry()
    token = registry.create("req-1", skill_name="sum")
    token.update_progress(ready_count=1, expected_count=3)
    time.sleep(0.05)

    snap = registry.snapshot()
    assert list(snap.keys()) == ["req-1"]
    info = snap["req-1"]
    assert info["skill"] == "sum"
    assert info["ready_count"] == 1
    assert info["expected_count"] == 3
    assert info["elapsed_seconds"] >= 0.05


def test_registry_snapshot_empty_when_nothing_tracked():
    registry = CancellationRegistry()
    assert registry.snapshot() == {}


def test_describe_in_flight_empty():
    assert "Nothing currently in flight" in describe_in_flight({})


def test_describe_in_flight_reports_skill_elapsed_and_progress():
    snapshot = {
        "req-1": {"skill": "median", "elapsed_seconds": 4.2, "ready_count": 2, "expected_count": 3},
    }
    description = describe_in_flight(snapshot)
    assert "req-1" in description
    assert "median" in description
    assert "4.2" in description
    assert "2 of 3" in description
    assert "1 still pending" in description


def test_describe_in_flight_handles_no_progress_reported_yet():
    snapshot = {"req-1": {"skill": "median", "elapsed_seconds": 0.1}}
    description = describe_in_flight(snapshot)
    assert "no contributor progress reported yet" in description


def test_describe_in_flight_all_contributors_checked_in():
    snapshot = {
        "req-1": {"skill": "median", "elapsed_seconds": 1.0, "ready_count": 3, "expected_count": 3},
    }
    description = describe_in_flight(snapshot)
    assert "all 3 of 3 contributors have checked in" in description
