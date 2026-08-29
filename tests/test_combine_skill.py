"""
End-to-end test of the combine skill across 3 real worker subprocesses and
a head running in-process, against real (disposable) Redis - same rigor as
test_median_skill.py/test_sum_skill.py: real Messenger, real subprocesses,
actual head.run_skill()/worker.py dispatch.

Unlike median/sum, combine has no per-worker data to gather - every worker
reports the "combine" capability (it ships in every image's skill registry,
same as any other skill), so run_skill() picks one at random as coordinator
and that one worker does the arithmetic. This test checks both the
arithmetic result and that it really ran on a worker, not the head - "head
never computes" is a design constraint, not just a comment.
"""
import os

from scarlet_agentic_harness import head as head_mod
from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.skills.registry import discover_skills
from tests.helpers import APP_ID, WORKER_DATA, spawn_worker, terminate_all, wait_for_workers


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


def test_combine_runs_on_a_worker_not_the_head(redis_conn_info):
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
        combine_skill = skills["combine"]

        wait_for_workers(head_buses, procs, "combine", expected_count=3)

        result = head_mod.run_skill(
            combine_skill,
            {"expression": "s2/n - (s1/n)**2", "variables": {"s1": 45.0, "s2": 285.0, "n": 9}},
            head_config,
            head_buses,
        )
        assert result["status"] == "ok", result
        assert abs(result["result"] - (285.0 / 9 - (45.0 / 9) ** 2)) < 1e-9
        assert head_config.agent_id not in result["detail"]
        assert any(node in result["detail"] for node in WORKER_DATA)
    finally:
        terminate_all(procs)


def test_combine_rejects_invalid_expression(redis_conn_info):
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
        combine_skill = skills["combine"]

        wait_for_workers(head_buses, procs, "combine", expected_count=3)

        result = head_mod.run_skill(
            combine_skill,
            {"expression": "__import__('os')", "variables": {}},
            head_config,
            head_buses,
        )
        assert result["status"] == "error", result
    finally:
        terminate_all(procs)
