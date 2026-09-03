"""
Real-LLM test - step 5 of the staged validation plan: does a real model
reliably follow _deliberate()'s WAIT/RETRY instruction, given a
natural-language coordinator status reply?

Deliberately isolated from any distributed machinery - see
test_real_llm_dialogue.py's module docstring for why a genuinely real,
non-artificial "head times out because a real coordinator is still
legitimately working" scenario can't actually be constructed with today's
fast, healthy skills. tests/test_deliberation.py already covers the
*mechanism* thoroughly (with a scripted LLM). What's genuinely uncertain,
and what this test actually validates, is narrower and honest: does the
real model's output reliably parse to the intended decision for realistic
inputs.
"""
import os

import pytest

from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.head import _deliberate
from scarlet_agentic_harness.llm.client import LLMClient
from tests.transcript import write_transcript

pytestmark = pytest.mark.skipif(
    not os.environ.get("LLM_BASE_URL"),
    reason="requires a real LLM backend - set LLM_BASE_URL/LLM_API_KEY/LLM_MODEL to run",
)

SCENARIOS = [
    (
        "still_working",
        "Still waiting on one contributor - it's always been my slowest, "
        "no errors reported, just taking a bit longer than usual.",
        True,  # should WAIT
    ),
    (
        "clearly_stuck",
        "I haven't heard from any contributors at all, and it's been well "
        "past when they should have checked in. Something looks wrong.",
        False,  # should RETRY
    ),
    (
        "almost_done",
        "Two of three contributors are in, just waiting on the last one, "
        "should be any moment now.",
        True,  # should WAIT
    ),
]


def test_deliberate_follows_the_wait_retry_instruction_for_realistic_replies():
    config = HarnessConfig(
        role="head", app_id="realllm_deliberate", node_address="head-node",
        device_group="realllm_deliberate_subagent", head_bus="realllm_deliberate_headagent",
        llm_base_url=os.environ["LLM_BASE_URL"],
        llm_api_key=os.environ.get("LLM_API_KEY"),
        llm_model=os.environ["LLM_MODEL"],
    )
    client = LLMClient(config)

    results = {}
    llm_conversation = []
    for name, reply, expected in SCENARIOS:
        should_wait = _deliberate(client, reply, coordinate_timeout=15.0)
        results[name] = (reply, should_wait, expected)
        llm_conversation.append({"role": "user", "content": f"[{name}] coordinator said: {reply!r}"})
        llm_conversation.append({"role": "assistant", "content": f"decided: {'WAIT' if should_wait else 'RETRY'}"})

    print("\n--- Deliberation results ---")
    for name, (reply, should_wait, expected) in results.items():
        got = "WAIT" if should_wait else "RETRY"
        want = "WAIT" if expected else "RETRY"
        print(f"{name}: {got} (expected {want}) - reply was: {reply!r}")

    summary = "\n".join(
        f"- {name}: got {'WAIT' if sw else 'RETRY'}, expected {'WAIT' if exp else 'RETRY'} "
        f"{'(match)' if sw == exp else '(MISMATCH)'}"
        for name, (_reply, sw, exp) in results.items()
    )
    path = write_transcript(
        "test_deliberate_follows_the_wait_retry_instruction_for_realistic_replies",
        bus_names={},  # no distributed messaging here - this is a direct LLM call, not head/coordinator/worker traffic
        llm_messages=llm_conversation,
        extra_notes=f"Model: {os.environ.get('LLM_MODEL')}\n\nResults:\n{summary}",
    )
    print(f"\nTranscript written to {path}")

    mismatches = [name for name, (_reply, sw, exp) in results.items() if sw != exp]
    assert not mismatches, f"deliberation disagreed with the expected decision for: {mismatches}"
