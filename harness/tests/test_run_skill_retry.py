"""
Tests head.run_skill()'s retry logic in isolation from any real skill's
computation - a fake "worker" is simulated by driving raw Messenger/Buses
traffic directly in this test process (via a router default_handler, the
same mechanism worker.start_dispatch() uses for real), standing in for what
a real worker subprocess would do. This makes the test deterministically
control *which* attempt succeeds, rather than depending on real timing or
killing a subprocess to reproduce a mid-computation failure - and no real
skill computation needs to exist for this, since only run_skill()'s own
attempt/retry control flow is under test.

reply_slack and coordinate_timeout are both shrunk here purely so this test
doesn't spend ~10+ real seconds waiting through the first (deliberately
unanswered) attempt's timeout.

Each test stops its routers in a finally block - a fake worker's
default_handler is a live Python closure in this process, and a
Buses/MessageRouter left running past its own test would keep replying to
*any* later test's dispatch that reaches it (skill capability names are
scoped per test, but the registry itself is shared, session-scoped Redis -
this bit a first draft of this file: an un-stopped fake worker from one
test kept eagerly answering the next test's requests).
"""
import os

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.skills.base import Skill
from tests.helpers import APP_ID, run_skill_sync


def _stop(buses: Buses) -> None:
    buses.global_router.stop()
    buses.local_router.stop()


class _StubSkill(Skill):
    """Test-only: coordinate()/contribute() are never actually invoked here -
    a fake worker (see below) answers on its behalf, so this only needs to
    exist to give run_skill() a name/coordinate_timeout/coordinator_for."""
    description = "test-only"
    coordinate_timeout = 0.5

    def __init__(self, name: str):
        self.name = name

    def contribute(self, ctx, request):
        raise AssertionError("never called - no real worker in this test")

    def coordinate(self, ctx, request, workers):
        raise AssertionError("never called on the head - a fake worker replies instead")

    def coordinator_for(self, ctx, workers):
        return workers[0]


def test_run_skill_retries_after_a_coordinator_timeout(redis_conn_info):
    base_env = dict(os.environ)
    base_env.update({
        "REDIS_HOST": redis_conn_info["host"],
        "REDIS_PORT": redis_conn_info["port"],
        "REDIS_AUTH_TOKEN": redis_conn_info["auth_token"],
    })
    os.environ.update(base_env)

    head_config = HarnessConfig(
        role="head", app_id=APP_ID, node_address="head-node-retry1",
        device_group=f"{APP_ID}_subagent", head_bus=f"{APP_ID}_headagent",
        llm_base_url=None, llm_api_key=None, llm_model=None,
    )
    head_buses = Buses(head_config)

    fake_worker_config = HarnessConfig(
        role="worker", app_id=APP_ID, node_address="fakeworker-retry1",
        device_group=f"{APP_ID}_subagent", head_bus=f"{APP_ID}_headagent",
        llm_base_url=None, llm_api_key=None, llm_model=None,
    )
    fake_worker_buses = Buses(fake_worker_config)
    fake_worker_buses.report_status(capabilities=["stub_retry_test_1"])

    seen = [0]
    replies_sent = []

    def fake_worker_handler(msg: dict) -> None:
        # Impersonates a real worker via the same router default_handler
        # mechanism worker.start_dispatch() uses for real (see buses.py/
        # router.py) - deliberately ignores the *first* skill_coordinate it
        # sees, so run_skill()'s first attempt times out, and only answers
        # the second (i.e. the retried attempt).
        body = msg.get("body", {})
        if body.get("type") != "skill_coordinate":
            return
        seen[0] += 1
        if seen[0] >= 2:
            fake_worker_buses.global_bus.Send(msg["from"], {
                "type": "skill_result",
                "request_id": body["request_id"],
                "status": "ok",
                "result": 99,
            })
            replies_sent.append(body["request_id"])

    fake_worker_buses.global_router.default_handler = fake_worker_handler

    try:
        skill = _StubSkill("stub_retry_test_1")
        result = run_skill_sync(skill, {}, head_config, head_buses, max_attempts=2, reply_slack=0.5)

        assert result["status"] == "ok"
        assert result["result"] == 99
        assert seen[0] == 2  # first attempt was seen and ignored, second answered
        assert len(replies_sent) == 1
    finally:
        _stop(head_buses)
        _stop(fake_worker_buses)


def test_retry_sends_skill_cancel_for_the_superseded_attempt(redis_conn_info):
    base_env = dict(os.environ)
    base_env.update({
        "REDIS_HOST": redis_conn_info["host"],
        "REDIS_PORT": redis_conn_info["port"],
        "REDIS_AUTH_TOKEN": redis_conn_info["auth_token"],
    })
    os.environ.update(base_env)

    head_config = HarnessConfig(
        role="head", app_id=APP_ID, node_address="head-node-retry3",
        device_group=f"{APP_ID}_subagent", head_bus=f"{APP_ID}_headagent",
        llm_base_url=None, llm_api_key=None, llm_model=None,
    )
    head_buses = Buses(head_config)

    fake_worker_config = HarnessConfig(
        role="worker", app_id=APP_ID, node_address="fakeworker-retry3",
        device_group=f"{APP_ID}_subagent", head_bus=f"{APP_ID}_headagent",
        llm_base_url=None, llm_api_key=None, llm_model=None,
    )
    fake_worker_buses = Buses(fake_worker_config)
    fake_worker_buses.report_status(capabilities=["stub_retry_test_3"])

    coordinate_seen = []
    cancels_seen = []

    def fake_worker_handler(msg: dict) -> None:
        body = msg.get("body", {})
        if body.get("type") == "skill_coordinate":
            coordinate_seen.append(body["request_id"])
            if len(coordinate_seen) >= 2:
                fake_worker_buses.global_bus.Send(msg["from"], {
                    "type": "skill_result", "request_id": body["request_id"], "status": "ok", "result": 1,
                })
            # else: first attempt - deliberately ignored, same as the retry test above
        elif body.get("type") == "skill_cancel":
            cancels_seen.append(body["request_id"])

    fake_worker_buses.global_router.default_handler = fake_worker_handler

    try:
        skill = _StubSkill("stub_retry_test_3")
        result = run_skill_sync(skill, {}, head_config, head_buses, max_attempts=2, reply_slack=0.5)

        assert result["status"] == "ok"
        assert len(coordinate_seen) == 2
        first_attempt_id, second_attempt_id = coordinate_seen
        # Exactly one cancel, for the *first* (superseded) attempt's
        # request_id - never for the one that actually succeeded.
        assert cancels_seen == [first_attempt_id]
        assert second_attempt_id not in cancels_seen
    finally:
        _stop(head_buses)
        _stop(fake_worker_buses)


def test_run_skill_gives_up_after_max_attempts_all_fail(redis_conn_info):
    base_env = dict(os.environ)
    base_env.update({
        "REDIS_HOST": redis_conn_info["host"],
        "REDIS_PORT": redis_conn_info["port"],
        "REDIS_AUTH_TOKEN": redis_conn_info["auth_token"],
    })
    os.environ.update(base_env)

    head_config = HarnessConfig(
        role="head", app_id=APP_ID, node_address="head-node-retry2",
        device_group=f"{APP_ID}_subagent", head_bus=f"{APP_ID}_headagent",
        llm_base_url=None, llm_api_key=None, llm_model=None,
    )
    head_buses = Buses(head_config)

    fake_worker_config = HarnessConfig(
        role="worker", app_id=APP_ID, node_address="fakeworker-retry2",
        device_group=f"{APP_ID}_subagent", head_bus=f"{APP_ID}_headagent",
        llm_base_url=None, llm_api_key=None, llm_model=None,
    )
    fake_worker_buses = Buses(fake_worker_config)
    fake_worker_buses.report_status(capabilities=["stub_retry_test_2"])
    # default_handler intentionally left unset - this fake worker never
    # replies to anything, so every attempt should time out.

    try:
        skill = _StubSkill("stub_retry_test_2")
        result = run_skill_sync(skill, {}, head_config, head_buses, max_attempts=2, reply_slack=0.5)

        assert result["status"] == "error"
        assert result["detail"] == "coordinator did not respond in time"
    finally:
        _stop(head_buses)
        _stop(fake_worker_buses)
