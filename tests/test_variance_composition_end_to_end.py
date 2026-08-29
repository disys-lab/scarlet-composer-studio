"""
The composability claim, proven by the system rather than asserted in a
docstring: two real `sum` invocations (transform=identity, transform=square)
plus one real `combine` invocation, all dispatched through
head.run_skill() across 3 real worker subprocesses and real Redis, produce
a variance that matches statistics.pvariance on the same data.

test_sum_skill.py already proves the *data* sum/n produce is composable (it
hand-computes the variance formula on r1/r2 and checks it). This test closes
the gap the README flagged ("no composition layer yet... proving the data
is composable, not yet that the system composes it"): the only arithmetic
this test itself performs is building the `variables` dict handed to
combine - the variance formula itself is evaluated by a worker, via
combine's safe_eval, not by test code.
"""
import os
import statistics

from scarlet_agentic_harness import head as head_mod
from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.skills.registry import discover_skills
from tests.helpers import APP_ID, WORKER_DATA, spawn_worker, terminate_all, wait_for_workers


def test_variance_via_two_sums_and_a_combine(redis_conn_info):
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

        wait_for_workers(head_buses, procs, "sum", expected_count=3)
        wait_for_workers(head_buses, procs, "combine", expected_count=3)

        r1 = head_mod.run_skill(skills["sum"], {"transform": "identity"}, head_config, head_buses)
        assert r1["status"] == "ok", r1
        r2 = head_mod.run_skill(skills["sum"], {"transform": "square"}, head_config, head_buses)
        assert r2["status"] == "ok", r2
        assert r1["n"] == r2["n"]

        r3 = head_mod.run_skill(
            skills["combine"],
            {
                "expression": "s2/n - (s1/n)**2",
                "variables": {"s1": r1["result"], "s2": r2["result"], "n": r1["n"]},
            },
            head_config,
            head_buses,
        )
        assert r3["status"] == "ok", r3

        all_numbers = [n for nums in WORKER_DATA.values() for n in nums]
        assert abs(r3["result"] - statistics.pvariance(all_numbers)) < 1e-9
    finally:
        terminate_all(procs)
