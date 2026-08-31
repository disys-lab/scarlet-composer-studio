"""
Real-LLM, real-MCP-protocol test: mcp_server.py's ask_scarlet_agent tool,
driven end to end by the real `mcp` client SDK (stdio transport) - not a
direct in-process call to head.converse(). This is what actually proves
the MCP gateway works: the client SDK spawns scarlet_agentic_harness.mcp_server
as a real subprocess, speaks the real MCP stdio protocol to it (initialize,
list_tools, call_tool), and that subprocess's own converse() call drives a
real distributed median computation across 3 real worker subprocesses and
real Redis - exactly the same computation tests/test_real_llm_median.py
verifies via a direct in-process converse_sync() call, but reached this
time through the MCP tool boundary instead.

Opt-in: skipped unless LLM_BASE_URL (and LLM_API_KEY/LLM_MODEL) are
actually set in the environment - same convention as every other
tests/test_real_llm_*.py file.
"""
import asyncio
import os
import statistics
import sys

import pytest

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from tests.helpers import WORKER_DATA, spawn_worker, terminate_all, wait_for_workers
from tests.transcript import write_transcript

pytestmark = pytest.mark.skipif(
    not os.environ.get("LLM_BASE_URL"),
    reason="requires a real LLM backend - set LLM_BASE_URL/LLM_API_KEY/LLM_MODEL to run",
)

APP_ID = "realllm_mcp"


async def _call_ask_scarlet_agent(mcp_env: dict, message: str):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "scarlet_agentic_harness.mcp_server"], env=mcp_env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            result = await session.call_tool("ask_scarlet_agent", {"message": message})
            return result, tool_names


def test_ask_scarlet_agent_drives_a_real_median_computation_over_real_mcp(redis_conn_info):
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

    mcp_env = dict(base_env)
    mcp_env.update({
        "ROLE": "head", "APP_ID": APP_ID, "NODE_ADDRESS": "mcp-head-node",
        "DEVICE_GROUP": head_config.device_group, "HEAD_BUS": head_config.head_bus,
    })

    procs = [spawn_worker(node, nums, base_env, app_id=APP_ID) for node, nums in WORKER_DATA.items()]
    tool_result = None
    tool_names: list[str] = []
    try:
        head_buses = Buses(head_config)  # test's own instance, only used to poll GatherStatus
        wait_for_workers(head_buses, procs, "median", expected_count=3)

        all_numbers = [n for nums in WORKER_DATA.values() for n in nums]
        expected = statistics.median(all_numbers)

        tool_result, tool_names = asyncio.run(_call_ask_scarlet_agent(
            mcp_env,
            "The worker agents each hold a private list of real numbers. "
            "What is the median across all of them?",
        ))

        print("\n--- MCP tools advertised ---")
        print(tool_names)
        print("\n--- MCP tool result (is_error=%s) ---" % tool_result.is_error)
        answer_text = "".join(
            block.text for block in tool_result.content if getattr(block, "type", None) == "text"
        )
        print(answer_text)

        assert "ask_scarlet_agent" in tool_names
        assert not tool_result.is_error, f"tool call ended in error: {answer_text}"
        assert str(expected) in answer_text or str(int(expected)) in answer_text, (
            f"expected median {expected} not found in the real model's answer: {answer_text!r}"
        )
    finally:
        terminate_all(procs)
        llm_messages = None
        if tool_result is not None:
            answer_text = "".join(
                block.text for block in tool_result.content if getattr(block, "type", None) == "text"
            )
            llm_messages = [
                {"role": "user", "content": "(via MCP tool call ask_scarlet_agent) The worker agents each "
                 "hold a private list of real numbers. What is the median across all of them?"},
                {"role": "assistant", "content": answer_text},
            ]
        path = write_transcript(
            "test_ask_scarlet_agent_drives_a_real_median_computation_over_real_mcp",
            bus_names,
            llm_messages=llm_messages,
            extra_notes=(
                f"Model: {os.environ.get('LLM_MODEL')}\n"
                f"Reached via the real MCP stdio protocol (mcp.client.stdio.stdio_client), not a direct "
                f"in-process converse() call - the client SDK spawned scarlet_agentic_harness.mcp_server "
                f"as a real subprocess and drove it over stdin/stdout.\n"
                f"Tools advertised by the server: {tool_names}"
            ),
        )
        print(f"\nTranscript written to {path}")
