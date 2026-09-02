"""
End-to-end test of list_tags across 2 real worker subprocesses and a head
running in-process, against real (disposable) Redis + Postgres - same
rigor and shape as test_query_feature_skill.py. Also covers the one real
difference from query_feature: a mode: broker entry raises a clear,
honest error (list_tags has no broker-relay path yet) rather than being
silently indistinguishable from "no worker has this source".
"""
import os
import subprocess
import sys

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.skills.registry import discover_skills
from tests.helpers import run_skill_sync, terminate_all, wait_for_workers

APP_ID = "ltagstest"


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


def test_list_tags_returns_real_schema_and_rejects_broker_mode_cleanly(redis_conn_info, tmp_path, postgres_conn_info):
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
  - name: central_erp
    type: mssql
    mode: broker
    description: "Corporate ERP inventory figures."
    broker_url: "https://broker.example.com"
""")

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
        list_tags_skill = skills["list_tags"]

        wait_for_workers(head_buses, procs, "list_tags", expected_count=2)

        print("=== real schema for a local source ===")
        r1 = run_skill_sync(list_tags_skill, {"source_name": "sensors_pg"}, head_config, head_buses)
        assert r1["status"] == "ok", r1
        # matches conftest.py's postgres_conn_info fixture's own real
        # schema exactly (CREATE TABLE sensors (name text, value float8))
        assert r1["result"] == [{"table": "public.sensors", "columns": ["name", "value"]}]

        print("=== mode: broker -> clean, honest error, not silently 'not found' ===")
        r2 = run_skill_sync(
            list_tags_skill, {"source_name": "central_erp"}, head_config, head_buses, timeout=25,
        )
        assert r2["status"] == "error", r2
        assert "not yet supported" in r2["detail"], r2

        print("=== not found: no worker has this source -> clean, non-retryable error ===")
        r3 = run_skill_sync(
            list_tags_skill, {"source_name": "nonexistent_source"}, head_config, head_buses, timeout=25,
        )
        assert r3["status"] == "error", r3
        assert r3["retryable"] is False, r3
    finally:
        terminate_all(procs)
