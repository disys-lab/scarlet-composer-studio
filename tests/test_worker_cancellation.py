"""
Real proof that cancellation actually stops a real skill's coordinate()
loop, not just that the plumbing exists: worker.start_dispatch() drives a
real MedianSkill instance, coordinate()'s wait loop is left genuinely
stuck (an expected contributor that never signals), a skill_cancel for the
same request_id arrives while it's still waiting, and the result comes
back quickly - well under coordinate_timeout - instead of running the
full timeout.

Driven by directly crafted skill_coordinate/skill_cancel messages, not
through run_skill()'s dispatch/retry - that path is exactly what
tests/test_run_skill_retry.py covers (a retry actually sends
skill_cancel). This test is about what happens on the receiving end once
one arrives - real router, real worker dispatch, real Skill, real Redis.
"""
import os
import time

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.skills.median import MedianSkill
from scarlet_agentic_harness import worker as worker_mod
from tests.helpers import APP_ID


def test_skill_cancel_stops_a_stuck_coordinate_call_quickly(redis_conn_info):
    base_env = dict(os.environ)
    base_env.update({
        "REDIS_HOST": redis_conn_info["host"],
        "REDIS_PORT": redis_conn_info["port"],
        "REDIS_AUTH_TOKEN": redis_conn_info["auth_token"],
    })
    os.environ.update(base_env)

    worker_config = HarnessConfig(
        role="worker", app_id=APP_ID, node_address="cancel-test-worker",
        device_group=f"{APP_ID}_subagent", head_bus=f"{APP_ID}_headagent",
        llm_base_url=None, llm_api_key=None, llm_model=None,
    )
    worker_buses = Buses(worker_config)

    head_config = HarnessConfig(
        role="head", app_id=APP_ID, node_address="cancel-test-head",
        device_group=f"{APP_ID}_subagent", head_bus=f"{APP_ID}_headagent",
        llm_base_url=None, llm_api_key=None, llm_model=None,
    )
    head_buses = Buses(head_config)

    try:
        skill = MedianSkill()
        skill.coordinate_timeout = 3.0  # short, so the test stays fast even if cancellation *didn't* work
        worker_mod.start_dispatch(worker_config, worker_buses, {"median": skill})

        request_id = "cancel-test-req-1"
        # Two expected contributors - this worker itself, and a phantom one
        # that will never signal ready - so coordinate()'s wait loop is
        # genuinely stuck until either the timeout or a cancel arrives.
        request = {
            "request_id": request_id,
            "skill": "median",
            "mapper_name": f"median_{request_id}",
            "coordinator": worker_config.agent_id,
            "workers": [worker_config.agent_id, f"{APP_ID}_phantom-worker"],
            "params": {},
        }
        head_buses.global_bus.Send(worker_config.agent_id, {"type": "skill_coordinate", **request})

        # Give coordinate() real time to actually start waiting before
        # cancelling - proves this is a genuine mid-flight cancel, not a
        # race where cancel arrives before contribute()/coordinate() began.
        time.sleep(1.0)
        started = time.time()
        head_buses.global_bus.Send(worker_config.agent_id, {"type": "skill_cancel", "request_id": request_id})

        result = head_buses.global_router.receive_for(request_id, timeout=5)
        elapsed = time.time() - started

        assert result is not None, "no skill_result arrived - cancellation did not stop coordinate()"
        body = result.get("body", {})
        assert body["status"] == "error"
        assert body["detail"] == "cancelled"
        assert body["retryable"] is False
        assert elapsed < 2.0, (
            f"took {elapsed:.2f}s to respond after cancel - coordinate_timeout "
            f"is 3.0s, a cancelled response should be near-instant, not close to it"
        )
    finally:
        worker_buses.global_router.stop()
        worker_buses.local_router.stop()
        head_buses.global_router.stop()
        head_buses.local_router.stop()
