"""
End-to-end test of the median skill across 3 real worker subprocesses and a
head running in-process - against a real (disposable) Redis, using the
actual Messenger/Mapper primitives and the actual head.run_skill() /
worker.py dispatch code, not a shortcut that calls skill methods directly.

Workers run as separate OS processes (python -m scarlet_agentic_harness)
rather than threads sharing one process, because the harness's LOCAL_NUMBERS
env var (and APP_ID/NODE_ADDRESS generally) are process-global by design -
this matches how it will actually run (separate containers), and avoids
inventing thread-local workarounds for something that's fundamentally
multi-process.
"""
import os
import statistics
import subprocess
import sys
import time

from scarlet_agentic_harness import head as head_mod
from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.skills.registry import discover_skills

APP_ID = "medtest"
WORKER_DATA = {
    "w1": [5.0, 1.0, 9.0],
    "w2": [3.0, 8.0],
    "w3": [2.0, 7.0, 4.0, 6.0],
}


def _spawn_worker(node_address: str, numbers: list[float], env: dict) -> subprocess.Popen:
    worker_env = dict(env)
    worker_env.update({
        "ROLE": "worker",
        "APP_ID": APP_ID,
        "NODE_ADDRESS": node_address,
        "LOCAL_NUMBERS": ",".join(str(n) for n in numbers),
    })
    return subprocess.Popen(
        [sys.executable, "-m", "scarlet_agentic_harness"],
        env=worker_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


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

    procs = [_spawn_worker(node, nums, base_env) for node, nums in WORKER_DATA.items()]
    try:
        head_config = HarnessConfig(
            role="head", app_id=APP_ID, node_address="head-node",
            device_group=f"{APP_ID}_subagent", head_bus=f"{APP_ID}_headagent",
            llm_base_url=None, llm_api_key=None, llm_model=None,
        )
        head_buses = Buses(head_config)
        skills = discover_skills()
        median_skill = skills["median"]

        # Wait for all 3 workers to register with the median capability
        # (real capability discovery via GatherStatus, not a fixed sleep).
        deadline = time.time() + 20
        seen = set()
        while time.time() < deadline and len(seen) < 3:
            for proc in procs:
                assert proc.poll() is None, f"worker process exited early: {proc.stderr.read()}"
            workers_info = head_buses.gather_workers()
            seen = {
                agent_id for agent_id, rec in workers_info.items()
                if "median" in rec.get("capabilities", [])
            }
            time.sleep(0.5)
        assert len(seen) == 3, f"only {len(seen)}/3 workers registered in time: {seen}"

        result = head_mod.run_skill(median_skill, {}, head_config, head_buses)

        all_numbers = [n for nums in WORKER_DATA.values() for n in nums]
        expected = statistics.median(all_numbers)

        assert result["status"] == "ok", result
        assert result["result"] == expected, (result, expected)
        assert "n=9" in result["detail"]
    finally:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
