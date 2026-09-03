"""
Verifies report_status()'s data_sources field (buses.py) and the periodic
refresh loop (__main__.py) against a real worker subprocess and real
disposable Redis - confirms a hand-edited ~/.scarlet/config.yaml is
reflected on the next GatherStatus() read within one refresh interval,
without restarting the worker, and that describe_sources() never leaks a
credential field over the wire.
"""
import os
import subprocess
import sys

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from tests.helpers import terminate_all

APP_ID = "dirtest"


def test_data_sources_report_and_refresh_pick_up_a_live_config_edit(redis_conn_info, tmp_path):
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text("""
sources:
  - name: source_a
    type: postgres
    mode: local
    description: "First source."
    host: 127.0.0.1
    port: 5432
    database: db
    user: u
    password: super-secret-password
""")

    worker_env = dict(os.environ)
    worker_env.update({
        "REDIS_HOST": redis_conn_info["host"],
        "REDIS_PORT": redis_conn_info["port"],
        "REDIS_AUTH_TOKEN": redis_conn_info["auth_token"],
        "ROLE": "worker",
        "APP_ID": APP_ID,
        "NODE_ADDRESS": "w1",
        "SCARLET_LOCAL_CONFIG": str(config_yaml),
        "DATA_SOURCE_REFRESH_INTERVAL": "2",
    })
    proc = subprocess.Popen(
        [sys.executable, "-m", "scarlet_agentic_harness"],
        env=worker_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        os.environ.update({
            "REDIS_HOST": redis_conn_info["host"],
            "REDIS_PORT": redis_conn_info["port"],
            "REDIS_AUTH_TOKEN": redis_conn_info["auth_token"],
        })
        head_config = HarnessConfig(
            role="head", app_id=APP_ID, node_address="head-node",
            device_group=f"{APP_ID}_subagent", head_bus=f"{APP_ID}_headagent",
            llm_base_url=None, llm_api_key=None, llm_model=None,
        )
        head_buses = Buses(head_config)

        import time
        agent_id = f"{APP_ID}_w1"
        deadline = time.time() + 20
        record = None
        while time.time() < deadline:
            assert proc.poll() is None, f"worker exited early: {proc.stderr.read()}"
            record = head_buses.gather_workers().get(agent_id)
            if record:
                break
            time.sleep(0.5)
        assert record is not None, "worker never registered"

        print("=== initial report reflects source_a, no credential fields ===")
        sources = record["data_sources"]
        assert sources == [
            {"name": "source_a", "type": "postgres", "mode": "local", "description": "First source."}
        ], sources
        for s in sources:
            assert "password" not in s and "user" not in s and "host" not in s, f"credential leaked: {s}"

        print("=== live edit: add source_b, wait for the refresh loop (2s interval) ===")
        config_yaml.write_text("""
sources:
  - name: source_a
    type: postgres
    mode: local
    description: "First source."
    host: 127.0.0.1
    port: 5432
    database: db
    user: u
    password: super-secret-password
  - name: source_b
    type: redis
    mode: local
    description: "Second source, added after startup."
    host: 127.0.0.1
""")

        deadline = time.time() + 15
        names = set()
        while time.time() < deadline:
            record = head_buses.gather_workers().get(agent_id)
            names = {s["name"] for s in (record or {}).get("data_sources", [])}
            if "source_b" in names:
                break
            time.sleep(0.5)
        assert names == {"source_a", "source_b"}, (
            f"refresh loop did not pick up the live config edit within 15s (saw {names})"
        )
        print("live edit picked up without a worker restart")
    finally:
        terminate_all([proc])
