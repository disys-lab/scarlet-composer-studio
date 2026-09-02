"""
CreateScarletSkill: proves it's dispatchable through the exact same generic
mechanism as median/sum (discoverable, invoked via run_skill()/
run_skill_sync() from the head - test 1), AND proves the actual point of
building it as a Skill rather than just a HarnessContext method: a worker
can dispatch it directly to its peers, using its own config/buses via
HarnessContext.invoke_skill(), with no head process constructed anywhere
in the test at all (test 2) - "without relying on the head", literally.

Real (disposable) Redis, real worker dispatch code (worker.start_dispatch()/
handle_message() - not reimplemented or shortcut), only the LLM backend is
faked (ScriptedLLMClient), same convention as the rest of this suite. Fake
workers run in-process (real start_dispatch() driving real MessageRouter
traffic over real Redis, just not a separate OS process) rather than real
subprocesses specifically because a real subprocess worker constructs its
own LLMClient from env vars in __main__.py, which can't be swapped for a
ScriptedLLMClient from outside the process - matching how test_scarlet_
minting.py already handles the same constraint.
"""
import json
import os

from scarlets.utils.ScarletUtils import redisConnect

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.cancellation import CancellationRegistry
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.skills.create_scarlet import CreateScarletSkill
from scarlet_agentic_harness.skills.registry import discover_skills
from scarlet_agentic_harness import worker as worker_mod
from tests.fakes import ScriptedLLMClient, assistant_tool_call
from tests.helpers import run_skill_sync


def _set_redis_env(redis_conn_info) -> None:
    os.environ.update({
        "REDIS_HOST": redis_conn_info["host"],
        "REDIS_PORT": redis_conn_info["port"],
        "REDIS_AUTH_TOKEN": redis_conn_info["auth_token"],
    })


def _worker_config(app_id: str, node_address: str) -> HarnessConfig:
    return HarnessConfig(
        role="worker", app_id=app_id, node_address=node_address,
        device_group=f"{app_id}_subagent", head_bus=f"{app_id}_headagent",
        llm_base_url=None, llm_api_key=None, llm_model=None,
    )


def _mint_response(name: str, description: str) -> list[dict]:
    return [assistant_tool_call("call_1", "mint_scarlet", {
        "name": name, "scarlet_type": "mapper", "description": description,
    })]


def _stop_all(*buses_list: Buses) -> None:
    for b in buses_list:
        b.global_router.stop()
        b.local_router.stop()


def test_create_scarlet_is_discoverable_alongside_the_math_skills():
    skills = discover_skills()
    assert "create_scarlet" in skills
    assert isinstance(skills["create_scarlet"], CreateScarletSkill)
    # Same shape as sum/median - a real tool schema an LLM tool-calling
    # loop (head.converse()) could pick, not a special-cased capability.
    schema = skills["create_scarlet"].as_tool_schema()
    assert schema["function"]["name"] == "create_scarlet"
    assert "purpose" in schema["function"]["parameters"]["properties"]


def test_head_dispatches_create_scarlet_the_same_way_as_any_math_skill(redis_conn_info):
    """Test 1: the ordinary path, proving nothing about this skill's own
    dispatch is special-cased versus sum/median - same run_skill_sync()
    call, same result shape."""
    _set_redis_env(redis_conn_info)
    app_id = "createscarlet1"

    head_config = HarnessConfig(
        role="head", app_id=app_id, node_address="head-node",
        device_group=f"{app_id}_subagent", head_bus=f"{app_id}_headagent",
        llm_base_url=None, llm_api_key=None, llm_model=None,
    )
    head_buses = Buses(head_config)

    w1_config = _worker_config(app_id, "w1")
    w1_buses = Buses(w1_config)
    w2_config = _worker_config(app_id, "w2")
    w2_buses = Buses(w2_config)

    skill = CreateScarletSkill()
    llm = ScriptedLLMClient(_mint_response(
        "grad_agg_headtest1", "Accumulates per-round gradient tensors from 2 peers.",
    ))

    try:
        for cfg, buses in ((w1_config, w1_buses), (w2_config, w2_buses)):
            buses.report_status(capabilities=["create_scarlet"])
            worker_mod.start_dispatch(cfg, buses, {"create_scarlet": skill}, llm_client=llm)

        result = run_skill_sync(
            skill, {"purpose": "aggregating a gradient tensor across 2 peers", "artifact_kind": "tensor"},
            head_config, head_buses,
        )

        assert result["status"] == "ok", result
        assert result["result"]["name"] == "grad_agg_headtest1"

        r = redisConnect(decode_responses=True)
        raw = r.get("scarlet_definition_grad_agg_headtest1")
        assert raw is not None
        entry = json.loads(raw)
        assert entry["description"] == "Accumulates per-round gradient tensors from 2 peers."
    finally:
        _stop_all(head_buses, w1_buses, w2_buses)


def test_worker_invokes_create_scarlet_on_its_peers_with_no_head_process_at_all(redis_conn_info):
    """
    Test 2: the actual capability being built. No HarnessConfig with
    role="head" and no head Buses is constructed anywhere in this test -
    an "invoker" worker dispatches create_scarlet directly to two peer
    workers via HarnessContext.invoke_skill(), exactly as a skill's own
    contribute()/coordinate() would mid-task. The result comes back to the
    invoker the same way run_skill_sync() delivers one to the head in the
    test above - because it's the same function underneath.
    """
    _set_redis_env(redis_conn_info)
    app_id = "createscarlet2"

    skill = CreateScarletSkill()
    llm = ScriptedLLMClient(_mint_response(
        "embedding_share_w2p1", "Shares one worker's computed embedding matrix with its peers.",
    ))

    peer1_config = _worker_config(app_id, "peer1")
    peer1_buses = Buses(peer1_config)
    peer2_config = _worker_config(app_id, "peer2")
    peer2_buses = Buses(peer2_config)

    # The invoking worker - deliberately never registered as a peer itself
    # (no report_status() call), just like a worker calling
    # ctx.invoke_skill() from inside its own contribute()/coordinate()
    # wouldn't dispatch the sub-skill to itself.
    invoker_config = _worker_config(app_id, "invoker")
    invoker_buses = Buses(invoker_config)
    invoker_registry = CancellationRegistry()
    invoker_token = invoker_registry.create("invoker-standin", skill_name="test-standin")

    try:
        for cfg, buses in ((peer1_config, peer1_buses), (peer2_config, peer2_buses)):
            buses.report_status(capabilities=["create_scarlet"])
            worker_mod.start_dispatch(cfg, buses, {"create_scarlet": skill}, llm_client=llm)

        # Prove this really is peer-to-peer: the invoker's own worker-role
        # buses sees exactly the 2 real peers it dispatched to, and nothing
        # resembling a head record - there is no head anywhere in this test.
        seen_peers = invoker_buses.gather_workers()
        assert set(seen_peers.keys()) == {peer1_config.agent_id, peer2_config.agent_id}

        invoker_ctx = HarnessContext(invoker_config, invoker_buses, cancellation=invoker_token)
        result = invoker_ctx.invoke_skill(
            skill, {"purpose": "sharing a computed embedding matrix with peer1/peer2", "artifact_kind": "matrix"},
        )

        assert result["status"] == "ok", result
        assert result["result"]["name"] == "embedding_share_w2p1"

        r = redisConnect(decode_responses=True)
        raw = r.get("scarlet_definition_embedding_share_w2p1")
        assert raw is not None
        entry = json.loads(raw)
        assert entry["description"] == "Shares one worker's computed embedding matrix with its peers."
    finally:
        invoker_registry.forget("invoker-standin")
        _stop_all(peer1_buses, peer2_buses, invoker_buses)
