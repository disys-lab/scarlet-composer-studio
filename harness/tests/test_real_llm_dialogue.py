"""
Real-LLM test - step 6 of the staged validation plan: AgentDialogue's real
reply generation. Given a check-in question and real injected context
(context_fn), does a real model produce a coherent reply that's actually
grounded in that context, not generic narration? This is the first place
in this whole codebase a *worker-side* LLM call is exercised against a
real backend (see dialogue.py's docstring - contribute()/coordinate()
deliberately never call an LLM, but a check-in reply is exactly the kind
of thing this harness is meant to compose).

A note on why this test doesn't attempt a full, real, end-to-end
distributed "head times out on a still-working coordinator" scenario:
median/sum complete well within any reasonable coordinate_timeout with
real, healthy subprocess workers, and coordinate()'s own internal deadline
always fires (producing a reply, even an error one) before the head's
outer wait ever would - there's no natural way to make a real worker
"stuck" without either faking it (tests/test_deliberation.py already does
this thoroughly, with a scripted LLM) or adding a deliberately slow
test-only skill to the production skill library, which we don't want to
do. What's genuinely uncertain, and what this test actually validates, is
narrower: does the real model produce a grounded, useful reply at all.

Real Buses/Redis (two agents - head and a stand-in coordinator - in the
same test process rather than separate subprocesses; AgentDialogue is fed
via handle() regardless of process boundaries, so this is a faithful test
of the dialogue layer specifically, not skill dispatch), so the existing
transcript mechanism captures real message traffic both ways.
"""
import os
import threading

import pytest

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.dialogue import AgentDialogue
from scarlet_agentic_harness.llm.client import LLMClient
from tests.transcript import write_transcript

pytestmark = pytest.mark.skipif(
    not os.environ.get("LLM_BASE_URL"),
    reason="requires a real LLM backend - set LLM_BASE_URL/LLM_API_KEY/LLM_MODEL to run",
)

APP_ID = "realllm_dialogue"


def test_agent_dialogue_produces_a_grounded_real_reply(redis_conn_info):
    os.environ.update({
        "REDIS_HOST": redis_conn_info["host"],
        "REDIS_PORT": redis_conn_info["port"],
        "REDIS_AUTH_TOKEN": redis_conn_info["auth_token"],
    })

    head_config = HarnessConfig(
        role="head", app_id=APP_ID, node_address="head-node",
        device_group=f"{APP_ID}_subagent", head_bus=f"{APP_ID}_headagent",
        llm_base_url=os.environ["LLM_BASE_URL"],
        llm_api_key=os.environ.get("LLM_API_KEY"),
        llm_model=os.environ["LLM_MODEL"],
    )
    coordinator_config = HarnessConfig(
        role="worker", app_id=APP_ID, node_address="coordinator-node",
        device_group=f"{APP_ID}_subagent", head_bus=f"{APP_ID}_headagent",
        llm_base_url=os.environ["LLM_BASE_URL"],
        llm_api_key=os.environ.get("LLM_API_KEY"),
        llm_model=os.environ["LLM_MODEL"],
    )
    bus_names = {"global": head_config.head_bus, "local": head_config.device_group}

    head_buses = Buses(head_config)
    coordinator_buses = Buses(coordinator_config)

    # Real grounding: this is the shape a real in-flight registry would
    # report (see cancellation.py's snapshot()/observability.py) -
    # hardcoded here since this test is specifically about AgentDialogue's
    # reply generation, not re-running the whole skill-dispatch machinery.
    fake_context = {
        "in_flight_requests": ["req-8f31c2", "req-91aa04"],
        "note": "2 of 3 contributors have checked in so far; the third has always been the slowest",
    }

    coordinator_dialogue = AgentDialogue(
        coordinator_buses.global_bus, LLMClient(coordinator_config), context_fn=lambda: fake_context,
    )
    coordinator_buses.global_router.default_handler = coordinator_dialogue.handle

    head_dialogue = AgentDialogue(head_buses.global_bus, LLMClient(head_config))
    head_buses.global_router.default_handler = head_dialogue.handle

    reply_box: dict = {}
    done = threading.Event()

    def on_reply(content, sender):
        reply_box["content"] = content
        reply_box["sender"] = sender
        done.set()

    try:
        head_dialogue.start(
            coordinator_config.agent_id,
            "You're coordinating a distributed computation that hasn't produced a final result yet. "
            "How is it going - are you still waiting on contributors, or has something gone wrong?",
            on_reply,
        )
        assert done.wait(timeout=30), "coordinator never replied to the check-in"

        print("\n--- Real coordinator reply ---")
        print(reply_box["content"])
        assert reply_box["sender"] == coordinator_config.agent_id

        content_lower = reply_box["content"].lower()
        grounded = "2" in reply_box["content"] or "two" in content_lower
        print(f"\nGrounded in injected context (mentions the '2 of 3' detail)? {grounded}")
        assert grounded, f"reply doesn't seem grounded in the injected context: {reply_box['content']!r}"
    finally:
        head_buses.global_router.stop()
        head_buses.local_router.stop()
        coordinator_buses.global_router.stop()
        coordinator_buses.local_router.stop()
        path = write_transcript(
            "test_agent_dialogue_produces_a_grounded_real_reply",
            bus_names,
            extra_notes=f"Model: {os.environ.get('LLM_MODEL')}\nInjected context (context_fn): {fake_context}",
        )
        print(f"\nTranscript written to {path}")
