"""
End-to-end test of the sum skill across 3 real worker subprocesses and a
head running in-process, against real (disposable) Redis - same rigor as
test_median_skill.py: real Messenger/Federator, real subprocesses, actual
head.run_skill()/worker.py dispatch, not a shortcut.

Covers both transform values (identity, square) since that parameter is the
whole point of this skill being a reusable building block rather than a
single-purpose one - and a third case verifying n and both sums together are
enough to hand-derive a variance, proving the composability claim, not just
asserting it in a docstring.
"""
import os

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.skills.registry import discover_skills
from tests.helpers import APP_ID, WORKER_DATA, run_skill_sync, spawn_worker, terminate_all, wait_for_workers


def _setup_env(redis_conn_info):
    base_env = dict(os.environ)
    base_env.update({
        "REDIS_HOST": redis_conn_info["host"],
        "REDIS_PORT": redis_conn_info["port"],
        "REDIS_AUTH_TOKEN": redis_conn_info["auth_token"],
    })
    os.environ.update({
        "REDIS_HOST": redis_conn_info["host"],
        "REDIS_PORT": redis_conn_info["port"],
        "REDIS_AUTH_TOKEN": redis_conn_info["auth_token"],
    })
    return base_env


def test_sum_identity_and_square_and_variance_composition(redis_conn_info):
    base_env = _setup_env(redis_conn_info)
    procs = [spawn_worker(node, nums, base_env) for node, nums in WORKER_DATA.items()]
    try:
        head_config = HarnessConfig(
            role="head", app_id=APP_ID, node_address="head-node",
            device_group=f"{APP_ID}_subagent", head_bus=f"{APP_ID}_headagent",
            llm_base_url=None, llm_api_key=None, llm_model=None,
        )
        head_buses = Buses(head_config)
        skills = discover_skills()
        sum_skill = skills["sum"]

        wait_for_workers(head_buses, procs, "sum", expected_count=3)

        all_numbers = [n for nums in WORKER_DATA.values() for n in nums]
        n = len(all_numbers)
        expected_s1 = sum(all_numbers)
        expected_s2 = sum(x * x for x in all_numbers)

        r1 = run_skill_sync(sum_skill, {"transform": "identity"}, head_config, head_buses)
        assert r1["status"] == "ok", r1
        assert r1["result"] == expected_s1
        assert r1["n"] == n  # total element count (9), not worker count (3)

        r2 = run_skill_sync(sum_skill, {"transform": "square"}, head_config, head_buses)
        assert r2["status"] == "ok", r2
        assert r2["result"] == expected_s2
        assert r2["n"] == n

        # default transform (no params at all) behaves as identity
        r3 = run_skill_sync(sum_skill, {}, head_config, head_buses)
        assert r3["status"] == "ok", r3
        assert r3["result"] == expected_s1

        # The actual composability claim: derive variance from S1, S2, and n
        # using nothing but arithmetic on the two sum results - no new
        # distributed protocol, no new skill.
        variance = expected_s2 / n - (expected_s1 / n) ** 2
        import statistics
        assert abs(variance - statistics.pvariance(all_numbers)) < 1e-9
    finally:
        terminate_all(procs)
