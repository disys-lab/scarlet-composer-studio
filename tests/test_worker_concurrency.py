"""
Proves the worker-level concurrency fix is correct, not just non-deadlocking:
two skill invocations in flight at once, forced onto the SAME worker as
coordinator, must not lose or cross-deliver each other's local-bus messages.

Before worker.start_dispatch()/MessageRouter, a worker handled one dispatch
message at a time via a blocking poll loop, so this scenario (one worker
still coordinating invocation A while invocation B's messages arrive)
couldn't even happen. router.py's docstring explains why a naive
thread-per-message change would have been unsafe without a router in front
of Receive(): scarlets' Messenger is an unfiltered, ack-on-read FIFO per
agent - a message meant for B could be silently consumed and lost by
whichever of A's or B's poll loop happened to call Receive() first.

Forces both invocations onto the same coordinator via coordinator_for() -
real random selection would only sometimes reproduce the scenario, and the
point is to guarantee it, not hope for it. coordinator_for() is only ever
called head-side (see head.run_skill), so patching it on the skill
instances discovered in this (head/test) process is sufficient - the worker
subprocesses just receive "coordinator": <id> as a plain field in the
dispatched request.
"""
import os
import statistics
import threading

from scarlet_agentic_harness import head as head_mod
from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.skills.registry import discover_skills
from tests.helpers import APP_ID, WORKER_DATA, spawn_worker, terminate_all, wait_for_workers


def test_two_concurrent_invocations_on_the_same_coordinator_both_succeed(redis_conn_info, monkeypatch):
    base_env = dict(os.environ)
    base_env.update({
        "REDIS_HOST": redis_conn_info["host"],
        "REDIS_PORT": redis_conn_info["port"],
        "REDIS_AUTH_TOKEN": redis_conn_info["auth_token"],
    })
    os.environ.update(base_env)

    procs = [spawn_worker(node, nums, base_env) for node, nums in WORKER_DATA.items()]
    try:
        head_config = HarnessConfig(
            role="head", app_id=APP_ID, node_address="head-node",
            device_group=f"{APP_ID}_subagent", head_bus=f"{APP_ID}_headagent",
            llm_base_url=None, llm_api_key=None, llm_model=None,
        )
        head_buses = Buses(head_config)
        skills = discover_skills()
        median_skill = skills["median"]
        sum_skill = skills["sum"]

        wait_for_workers(head_buses, procs, "median", expected_count=3)
        wait_for_workers(head_buses, procs, "sum", expected_count=3)

        forced_coordinator = f"{APP_ID}_w1"
        monkeypatch.setattr(median_skill, "coordinator_for", lambda ctx, workers: forced_coordinator)
        monkeypatch.setattr(sum_skill, "coordinator_for", lambda ctx, workers: forced_coordinator)

        results: dict = {}

        def run_median():
            results["median"] = head_mod.run_skill(median_skill, {}, head_config, head_buses)

        def run_sum():
            results["sum"] = head_mod.run_skill(sum_skill, {"transform": "identity"}, head_config, head_buses)

        t1 = threading.Thread(target=run_median)
        t2 = threading.Thread(target=run_sum)
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        assert not t1.is_alive() and not t2.is_alive(), "one of the concurrent invocations never returned"

        all_numbers = [n for nums in WORKER_DATA.values() for n in nums]
        assert results["median"]["status"] == "ok", results["median"]
        assert results["median"]["result"] == statistics.median(all_numbers)
        assert results["sum"]["status"] == "ok", results["sum"]
        assert results["sum"]["result"] == sum(all_numbers)
    finally:
        terminate_all(procs)
