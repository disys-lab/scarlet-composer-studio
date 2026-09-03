"""
Real-LLM test - step 4 of the staged validation plan, and the harder case:
can a real model actually compose sum(identity) -> sum(square) -> combine
into a correct variance, on its own, from a plain natural-language
question? Nothing in combine's tool description spells out the variance
*formula* - the model has to know or reconstruct s2/n - (s1/n)**2 itself
and phrase it as a safe_eval-compatible expression. This is the real test
of the "skills as alphabets, agents build paragraphs" thesis this whole
project is built around, not just "can the model pick one tool."

Opt-in: skipped unless LLM_BASE_URL is set - see test_real_llm_median.py
for the same pattern this follows (unique APP_ID for a clean transcript,
real subprocess workers, real Redis).
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

APP_ID = "realllm_variance"


def test_converse_composes_variance_from_two_sums_and_a_combine(redis_conn_info):
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
    result = None
    try:
        head_buses = Buses(head_config)
        skills = discover_skills()
        llm_client = LLMClient(head_config)

        wait_for_workers(head_buses, procs, "sum", expected_count=3)
        wait_for_workers(head_buses, procs, "combine", expected_count=3)

        all_numbers = [n for nums in WORKER_DATA.values() for n in nums]
        expected_variance = statistics.pvariance(all_numbers)

        result = converse_sync(
            "The worker agents each hold a private list of real numbers. "
            "What is the population variance across all of them? You have "
            "sum and combine tools available, not a dedicated variance tool.",
            head_config, head_buses, skills, llm_client,
            timeout=90, max_turns=8,
        )

        print("\n--- Real LLM final answer ---")
        print(result.answer)

        tool_calls_made = [
            tc["name"] for m in result.messages if m.get("role") == "assistant"
            for tc in (m.get("tool_calls") or [])
        ]
        print("\n--- Tools called, in order ---")
        print(tool_calls_made)

        combine_results = [
            m["content"] for m in result.messages
            if m.get("role") == "tool" and isinstance(m.get("content"), dict) and "result" in m["content"]
        ]
        got_variance = any(
            r.get("status") == "ok" and abs(r.get("result", float("nan")) - expected_variance) < 1e-6
            for r in combine_results
        )
        assert got_variance, (
            f"no tool result matched the expected variance {expected_variance} - "
            f"tools called: {tool_calls_made}, results: {combine_results}"
        )
    finally:
        terminate_all(procs)
        path = write_transcript(
            "test_converse_composes_variance_from_two_sums_and_a_combine",
            bus_names,
            llm_messages=result.messages if result is not None else None,
            extra_notes=f"Model: {os.environ.get('LLM_MODEL')}\nExpected variance: see test assertions.",
        )
        print(f"\nTranscript written to {path}")
