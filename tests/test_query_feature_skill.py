"""
End-to-end test of query_feature across 2 real worker subprocesses and a
head running in-process, against real (disposable) Redis - same rigor as
test_sum_skill.py. One worker's local config actually has the requested
source (a real Postgres container), the other's doesn't - proving the
self-filter-in-contribute()/first-response-wins-in-coordinate() shape
(see skills/query_feature.py's own module docstring) with real dispatch,
not a shortcut.
"""
import os
import subprocess
import sys

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.skills.registry import discover_skills
from tests.helpers import run_skill_sync, terminate_all, wait_for_workers

APP_ID = "qftest"


def _spawn_worker(node_address: str, env: dict, local_config_path: str | None) -> subprocess.Popen:
    worker_env = dict(env)
    worker_env.update({"ROLE": "worker", "APP_ID": APP_ID, "NODE_ADDRESS": node_address})
    if local_config_path:
        worker_env["SCARLET_LOCAL_CONFIG"] = local_config_path
    else:
        worker_env.pop("SCARLET_LOCAL_CONFIG", None)
    return subprocess.Popen(
        [sys.executable, "-m", "scarlet_agentic_harness"],
        env=worker_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def test_query_feature_finds_the_matching_worker_and_reports_not_found_cleanly(redis_conn_info, tmp_path, postgres_conn_info):
    base_env = dict(os.environ)
    base_env.update({
        "REDIS_HOST": redis_conn_info["host"],
        "REDIS_PORT": redis_conn_info["port"],
        "REDIS_AUTH_TOKEN": redis_conn_info["auth_token"],
    })
    # head_buses below is constructed in *this* process, not a subprocess -
    # Buses() reads REDIS_HOST/etc. straight from os.environ too (same as
    # test_sum_skill.py's _setup_env() does both for exactly this reason).
    os.environ.update({
        "REDIS_HOST": redis_conn_info["host"],
        "REDIS_PORT": redis_conn_info["port"],
        "REDIS_AUTH_TOKEN": redis_conn_info["auth_token"],
    })

    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text(f"""
sources:
  - name: sensors_pg
    type: postgres
    mode: local
    description: "Test sensor readings."
    host: {postgres_conn_info['host']}
    port: {postgres_conn_info['port']}
    database: {postgres_conn_info['database']}
    user: {postgres_conn_info['user']}
    password: {postgres_conn_info['password']}
""")

    # w1 has the matching local source, w2 doesn't (empty/no local config
    # at all) - both have the query_feature skill (it's always bundled),
    # only one actually matches the requested source_name.
    procs = [
        _spawn_worker("w1", base_env, str(config_yaml)),
        _spawn_worker("w2", base_env, None),
    ]
    try:
        head_config = HarnessConfig(
            role="head", app_id=APP_ID, node_address="head-node",
            device_group=f"{APP_ID}_subagent", head_bus=f"{APP_ID}_headagent",
            llm_base_url=None, llm_api_key=None, llm_model=None,
        )
        head_buses = Buses(head_config)
        skills = discover_skills()
        query_feature_skill = skills["query_feature"]

        wait_for_workers(head_buses, procs, "query_feature", expected_count=2)

        print("=== authorized: exactly one worker has sensors_pg ===")
        r1 = run_skill_sync(
            query_feature_skill,
            {"source_name": "sensors_pg", "query_payload": {"query": "SELECT name, value FROM sensors"}},
            head_config, head_buses,
        )
        assert r1["status"] == "ok", r1
        assert r1["result"] == {"columns": ["name", "value"], "rows": [["roll_speed", 1200.5]]}

        print("=== not found: no worker has this source -> clean, non-retryable error ===")
        # The 15s wait happens inside coordinate() on whichever worker
        # subprocess gets chosen as coordinator - mutating this skill
        # object's coordinate_timeout here has no effect on it (that's a
        # separate process with its own freshly-constructed instance), so
        # the test's own timeout has to cover the real default instead.
        r2 = run_skill_sync(
            query_feature_skill,
            {"source_name": "nonexistent_source", "query_payload": {}},
            head_config, head_buses,
            timeout=25,
        )
        assert r2["status"] == "error", r2
        assert r2["retryable"] is False, r2
        assert "nonexistent_source" in r2["detail"]
    finally:
        terminate_all(procs)
