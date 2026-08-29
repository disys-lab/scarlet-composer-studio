"""
The full stack together: head.converse()'s loop driving a real distributed
median computation across 3 real worker subprocesses and a real (disposable)
Redis - only the LLM's tool-call *decision* is scripted (there's no real
backend yet), everything downstream of that decision is the actual code
path: real Messenger/Mapper, real subprocesses, real run_skill() dispatch.
"""
import os
import statistics

from scarlet_agentic_harness import head as head_mod
from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.skills.registry import discover_skills
from tests.fakes import ScriptedLLMClient, assistant_final, assistant_tool_call
from tests.helpers import APP_ID, WORKER_DATA, spawn_worker, terminate_all, wait_for_workers


def test_converse_drives_a_real_median_computation(redis_conn_info):
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

        wait_for_workers(head_buses, procs, "median", expected_count=3)

        all_numbers = [n for nums in WORKER_DATA.values() for n in nums]
        expected = statistics.median(all_numbers)

        # The model's decision to call "median" is scripted (no real LLM
        # backend exists yet) - but its second turn's text has to reference
        # the *actual* computed value, proving the real distributed result
        # made it all the way back into the conversation, not a canned one.
        llm = ScriptedLLMClient([
            assistant_tool_call("call_1", "median"),
            assistant_final(f"The median is {expected}."),
        ])

        answer = head_mod.converse(
            "What's the median?", head_config, head_buses, skills, llm, max_turns=3,
        )

        assert answer == f"The median is {expected}."

        # the tool result fed back to the model on turn 2 must be the real,
        # correctly-computed distributed result - not a stub
        second_call_messages, _ = llm.calls[1]
        tool_result = [m for m in second_call_messages if m["role"] == "tool"][0]["content"]
        assert tool_result["status"] == "ok"
        assert tool_result["result"] == expected
        assert "n=9" in tool_result["detail"]
    finally:
        terminate_all(procs)
