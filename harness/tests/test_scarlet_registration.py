"""
Covers head.run_skill()'s scarlet pre-registration: before dispatching to
any worker, the head registers every scarlet_definition_* key a skill's
contribute()/coordinate() will construct (see Skill.scarlet_names()), with
a real, LLM-composed description when a ChatClient is available - so it's
visible on the Scarlets tracker the moment work starts, not only lazily
once some worker constructs its own (blank-description) Mapper()/Federator().

Uses real worker subprocesses and real (disposable) Redis - same rigor as
test_sum_skill.py/test_median_skill.py, not a shortcut. The one thing that's
faked is the LLM backend (ScriptedLLMClient), same convention as
test_deliberation.py.

register_scarlet_definition is patched with a spy that still calls through
to the real implementation - this captures exactly what head registered
(name/description) without depending on scanning shared, session-long-lived
Redis state (which could pick up an unrelated dispatch from another test
using the same "sum"/"median" skill names), while still proving the write
actually landed in real Redis and survived the worker's own later,
blank-description construction of the same key.
"""
import os
from unittest.mock import patch

from scarlets.utils.ScarletUtils import redisConnect
from scarlets.utils.ScarletUtils import register_scarlet_definition as real_register_scarlet_definition

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.skills.registry import discover_skills
from tests.fakes import ScriptedLLMClient, assistant_final
from tests.helpers import APP_ID, WORKER_DATA, run_skill_sync, spawn_worker, terminate_all, wait_for_workers


def _setup_env(redis_conn_info):
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
    return base_env


def test_sum_dispatch_preregisters_both_federator_scarlets_with_llm_description(redis_conn_info):
    base_env = _setup_env(redis_conn_info)
    procs = [spawn_worker(node, nums, base_env) for node, nums in WORKER_DATA.items()]
    try:
        head_config = HarnessConfig(
            role="head", app_id=APP_ID, node_address="head-node-scarlet1",
            device_group=f"{APP_ID}_subagent", head_bus=f"{APP_ID}_headagent",
            llm_base_url=None, llm_api_key=None, llm_model=None,
        )
        head_buses = Buses(head_config)
        skills = discover_skills()
        sum_skill = skills["sum"]
        wait_for_workers(head_buses, procs, "sum", expected_count=3)

        llm_client = ScriptedLLMClient([
            assistant_final("Holds this dispatch's partial sums, keyed by worker; the coordinator folds them into one total."),
        ])

        with patch(
            "scarlet_agentic_harness.head.register_scarlet_definition",
            side_effect=real_register_scarlet_definition,
        ) as spy:
            result = run_skill_sync(
                sum_skill, {"transform": "identity"}, head_config, head_buses, llm_client=llm_client,
            )
            assert result["status"] == "ok", result

            # Registered exactly once per Federator-derived name, before any
            # worker reply could have arrived (dispatch itself is
            # synchronous with this call in attempt()).
            registered_names = sorted(call.kwargs["scarlet_name"] for call in spy.call_args_list)
            mapper_name = next(
                n.rsplit("_mapper_global", 1)[0] for n in registered_names if n.endswith("_mapper_global")
            )
            assert registered_names == sorted([
                f"{mapper_name}_mapper_reducer", f"{mapper_name}_mapper_global",
            ])
            for call in spy.call_args_list:
                assert call.kwargs["description"] == (
                    "Holds this dispatch's partial sums, keyed by worker; the "
                    "coordinator folds them into one total."
                )
                assert call.kwargs["scarlet_type"] == "mapper"
                assert call.kwargs["overwrite"] is True

        # The LLM call itself was grounded in this specific dispatch, not
        # generic boilerplate - the skill name and the actual params show up
        # in what was sent to the model.
        assert len(llm_client.calls) == 1
        prompt = llm_client.calls[0][0][0]["content"]
        assert "'sum'" in prompt
        assert "identity" in prompt

        # Real end-to-end proof, not just "the spy was called": the
        # description that survives in real Redis is head's rich one, not
        # the blank string every worker's own ctx.federator() call passes -
        # proving register_scarlet_definition's overwrite=False default
        # protected it, exactly as documented.
        r = redisConnect(decode_responses=True)
        for name in registered_names:
            raw = r.get(f"scarlet_definition_{name}")
            assert raw is not None, f"{name} was never actually written to Redis"
            import json
            entry = json.loads(raw)
            assert entry["description"] == (
                "Holds this dispatch's partial sums, keyed by worker; the "
                "coordinator folds them into one total."
            )
            assert entry["scarlet_attributes"]["mode"] == "redis-scarlet"
    finally:
        terminate_all(procs)


def test_median_dispatch_preregisters_one_mapper_scarlet_without_llm(redis_conn_info):
    """No llm_client given (the common case for callers that don't opt into
    deliberation) - registration still happens, using the plain template
    fallback rather than silently skipping."""
    base_env = _setup_env(redis_conn_info)
    procs = [spawn_worker(node, nums, base_env) for node, nums in WORKER_DATA.items()]
    try:
        head_config = HarnessConfig(
            role="head", app_id=APP_ID, node_address="head-node-scarlet2",
            device_group=f"{APP_ID}_subagent", head_bus=f"{APP_ID}_headagent",
            llm_base_url=None, llm_api_key=None, llm_model=None,
        )
        head_buses = Buses(head_config)
        skills = discover_skills()
        median_skill = skills["median"]
        wait_for_workers(head_buses, procs, "median", expected_count=3)

        with patch(
            "scarlet_agentic_harness.head.register_scarlet_definition",
            side_effect=real_register_scarlet_definition,
        ) as spy:
            result = run_skill_sync(median_skill, {}, head_config, head_buses)
            assert result["status"] == "ok", result

            assert len(spy.call_args_list) == 1
            call = spy.call_args_list[0]
            assert call.kwargs["scarlet_name"].startswith("median_")
            assert call.kwargs["description"] == (
                f"Scarlet {call.kwargs['scarlet_name']!r} backing a 'median' "
                f"computation (params={{}})."
            )
    finally:
        terminate_all(procs)


def test_combine_skill_declares_no_scarlets():
    """combine computes purely locally (safe_eval over already-known values,
    no cross-worker Mapper/Federator use) - the base class default applies
    unmodified, so run_skill() registers nothing for it."""
    skills = discover_skills()
    combine_skill = skills["combine"]
    assert combine_skill.scarlet_names("combine_some-request-id") == []
