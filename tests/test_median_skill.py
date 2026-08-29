"""
End-to-end test of the median skill across 3 real worker subprocesses and a
head running in-process - against a real (disposable) Redis, using the
actual Messenger/Mapper primitives and the actual head.run_skill() /
worker.py dispatch code, not a shortcut that calls skill methods directly.
"""
import os
import statistics

from scarlet_agentic_harness import head as head_mod
from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.skills.registry import discover_skills
from tests.helpers import APP_ID, WORKER_DATA, spawn_worker, terminate_all, wait_for_workers


def test_median_across_three_worker_processes(redis_conn_info):
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

        wait_for_workers(head_buses, procs, "median", expected_count=3)

        result = head_mod.run_skill(median_skill, {}, head_config, head_buses)

        all_numbers = [n for nums in WORKER_DATA.values() for n in nums]
        expected = statistics.median(all_numbers)

        assert result["status"] == "ok", result
        assert result["result"] == expected, (result, expected)
        assert "n=9" in result["detail"]
    finally:
        terminate_all(procs)
