"""
Real-LLM test - step 3 of the staged validation plan: head.converse()
driving a real median computation across 3 real worker subprocesses and
real Redis, with the model's tool-call *decision* made by a real LLM
backend instead of tests/fakes.py's ScriptedLLMClient.

Opt-in: skipped unless LLM_BASE_URL (and LLM_API_KEY/LLM_MODEL) are
actually set in the environment. Unlike the rest of this suite, this
costs real money/time and depends on a real backend's behavior, not
just our own code.

A unique APP_ID keeps this test's bus namespace from colliding with any
other test's traffic - transcript capture (transcript.py) scans an
*entire* bus by name, so sharing one with another test would mix their
messages together.

The model's exact phrasing of the final answer isn't asserted strictly
(real models vary in wording) - what's asserted is the actual tool
result data in the retained message transcript (result.messages), which
is exact regardless of how the model narrates it.
"""
import os
import statistics

import pytest

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.llm.client import LLMClient
from scarlet_agentic_harness.skills.registry import discover_skills
from tests.helpers import WORKER_DATA, converse_sync, spawn_worker, terminate_all, wait_for_workers
from tests.transcript import write_transcript

pytestmark = pytest.mark.skipif(
    not os.environ.get("LLM_BASE_URL"),
    reason="requires a real LLM backend - set LLM_BASE_URL/LLM_API_KEY/LLM_MODEL to run",
)

APP_ID = "realllm_median"


def test_converse_drives_a_real_median_computation_with_a_real_llm(redis_conn_info):
    base_env = dict(os.environ)
    base_env.update({
        "REDIS_HOST": redis_conn_info["host"],
        "REDIS_PORT": redis_conn_info["port"],
        "REDIS_AUTH_TOKEN": redis_conn_info["auth_token"],
    })
    os.environ.update(base_env)

    head_config = HarnessConfig(
        role="head", app_id=APP_ID, node_address="head-node",
        device_group=f"{APP_ID}_subagent", head_bus=f"{APP_ID}_headagent",
        llm_base_url=os.environ["LLM_BASE_URL"],
        llm_api_key=os.environ.get("LLM_API_KEY"),
        llm_model=os.environ["LLM_MODEL"],
    )
    bus_names = {"global": head_config.head_bus, "local": head_config.device_group}

    procs = [spawn_worker(node, nums, base_env, app_id=APP_ID) for node, nums in WORKER_DATA.items()]
    result = None  # set inside try; may stay None if converse_sync itself raises
    try:
        head_buses = Buses(head_config)
        skills = discover_skills()
        llm_client = LLMClient(head_config)

        wait_for_workers(head_buses, procs, "median", expected_count=3)

        all_numbers = [n for nums in WORKER_DATA.values() for n in nums]
        expected = statistics.median(all_numbers)

        result = converse_sync(
            "The worker agents each hold a private list of real numbers. "
            "What is the median across all of them?",
            head_config, head_buses, skills, llm_client,
            timeout=60,
        )

        print("\n--- Real LLM final answer ---")
        print(result.answer)

        tool_results = [m["content"] for m in result.messages if m.get("role") == "tool"]
        assert any(
            isinstance(r, dict) and r.get("status") == "ok" and r.get("result") == expected
            for r in tool_results
        ), f"no tool result matched the expected median {expected} - got {tool_results}"
    finally:
        terminate_all(procs)
        path = write_transcript(
            "test_converse_drives_a_real_median_computation_with_a_real_llm",
            bus_names,
            llm_messages=result.messages if result is not None else None,
            extra_notes=f"Model: {os.environ.get('LLM_MODEL')}\nExpected median: see test assertions.",
        )
        print(f"\nTranscript written to {path}")
