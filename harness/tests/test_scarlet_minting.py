"""
Covers HarnessContext.mint_scarlet()/scarlet_minting.py: a worker minting
its own ad hoc scarlet via real LLM reasoning, mid-task - distinct from
head.py's dispatch-time _register_scarlets (which only ever generates a
*description*, never a name - see that module's docstring for why). Here
the LLM genuinely chooses the name too, which is safe specifically because
this function's own caller is what uses the returned name next, so nothing
else can drift out of sync with it.

Against real (disposable) Redis, same rigor as the rest of this suite - the
only thing faked is the model's response (ScriptedLLMClient), not Redis or
the actual registration code path.
"""
import json
import os

import pytest

from scarlets.utils.ScarletUtils import redisConnect

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.cancellation import CancellationRegistry
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.scarlet_minting import MINT_SCARLET_TOOL, ScarletMintingFailed, mint_scarlet_with_reasoning
from scarlet_agentic_harness.skills.base import Skill
from scarlet_agentic_harness import worker as worker_mod
from tests.fakes import ScriptedLLMClient, assistant_final, assistant_tool_call


def _worker_config(redis_conn_info, node_address: str) -> HarnessConfig:
    os.environ.update({
        "REDIS_HOST": redis_conn_info["host"],
        "REDIS_PORT": redis_conn_info["port"],
        "REDIS_AUTH_TOKEN": redis_conn_info["auth_token"],
    })
    return HarnessConfig(
        role="worker", app_id="minttest", node_address=node_address,
        device_group="minttest_subagent", head_bus="minttest_headagent",
        llm_base_url=None, llm_api_key=None, llm_model=None,
    )


def test_mint_scarlet_with_reasoning_registers_the_llm_chosen_name(redis_conn_info):
    config = _worker_config(redis_conn_info, "mint-node-1")
    llm = ScriptedLLMClient([
        assistant_tool_call("call_1", "mint_scarlet", {
            "name": "feature_cache_mint1",
            "scarlet_type": "mapper",
            "description": "Caches this worker's derived feature vector for reuse by later requests.",
        }),
    ])

    name = mint_scarlet_with_reasoning(llm, config.agent_id, "I just computed an expensive feature vector worth caching.")

    assert name == "feature_cache_mint1"
    # Prompted with the real motivation, not a generic template - and
    # grounded in what a scarlet actually is (SCARLET_TUTORIAL), not just
    # the bare tool schema.
    prompt = llm.calls[0][0][0]["content"]
    assert "expensive feature vector" in prompt
    assert "mapper" in prompt and "messenger" in prompt and "AllGather" in prompt
    assert llm.calls[0][1] == [MINT_SCARLET_TOOL]

    r = redisConnect(decode_responses=True)
    raw = r.get("scarlet_definition_feature_cache_mint1")
    assert raw is not None
    entry = json.loads(raw)
    assert entry["scarlet_type"] == "mapper"
    assert entry["description"] == "Caches this worker's derived feature vector for reuse by later requests."
    assert entry["scarlet_attributes"]["mode"] == "redis-scarlet"


def test_mint_scarlet_raises_when_model_does_not_call_the_tool(redis_conn_info):
    config = _worker_config(redis_conn_info, "mint-node-2")
    llm = ScriptedLLMClient([assistant_final("Sure, I'll get right on that.")])

    with pytest.raises(ScarletMintingFailed):
        mint_scarlet_with_reasoning(llm, config.agent_id, "some motivation")


def test_ctx_mint_scarlet_raises_immediately_without_an_llm_client(redis_conn_info):
    config = _worker_config(redis_conn_info, "mint-node-3")
    buses = Buses(config)
    try:
        ctx = HarnessContext(config, buses)  # llm_client defaults to None
        with pytest.raises(RuntimeError, match="no LLM backend configured"):
            ctx.mint_scarlet("doesn't matter, should never reach the model")
    finally:
        buses.global_router.stop()
        buses.local_router.stop()


def test_worker_handle_message_threads_llm_client_into_ctx_mint_scarlet(redis_conn_info):
    """
    Proves the plumbing, not just the primitive: a skill's own
    contribute() calling ctx.mint_scarlet() from inside a real
    worker.handle_message() call (the same function start_dispatch() wires
    up for a real worker process) actually reaches a real llm_client and
    writes to real Redis - not just that HarnessContext/scarlet_minting
    work in isolation.
    """
    config = _worker_config(redis_conn_info, "mint-node-4")
    buses = Buses(config)
    registry = CancellationRegistry()

    minted_name = {}

    class _MintingSkill(Skill):
        name = "mint_test_skill"
        description = "test-only"

        def contribute(self, ctx, request):
            minted_name["name"] = ctx.mint_scarlet("This request needs a scratch buffer for intermediate results.")

        def coordinate(self, ctx, request, workers):
            raise AssertionError("never called - this test only exercises skill_contribute")

    llm = ScriptedLLMClient([
        assistant_tool_call("call_1", "mint_scarlet", {
            "name": "scratch_buffer_mint4",
            "scarlet_type": "mapper",
            "description": "Intermediate scratch storage for this in-flight request only.",
        }),
    ])

    skill = _MintingSkill()
    token = registry.create("req-mint4", skill_name=skill.name)
    try:
        worker_mod.handle_message(
            {"from": "someone", "body": {"type": "skill_contribute", "request_id": "req-mint4", "skill": skill.name}},
            config, buses, {skill.name: skill}, token, llm_client=llm,
        )
    finally:
        registry.forget("req-mint4")
        buses.global_router.stop()
        buses.local_router.stop()

    assert minted_name["name"] == "scratch_buffer_mint4"
    r = redisConnect(decode_responses=True)
    assert r.exists("scarlet_definition_scratch_buffer_mint4")
