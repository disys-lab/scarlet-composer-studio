"""
Real-LLM, real-distributed, real-timing test: the full deliberation
pipeline end to end, with nothing faked - real subprocess workers, real
coordinator (with its own real LLM access via AgentDialogue, wired
exactly as __main__.py wires it for real), real check-in conversation,
real deliberation call, all against Claude.

The trick, since real healthy workers finish too fast to naturally time
out the head: only the HEAD's own in-process copy of the skill's
coordinate_timeout is shrunk (skill.coordinate_timeout is mutated on the
object *this test* passed into run_skill() - a completely separate Python
object from whatever coordinate_timeout the worker subprocess's own
discover_skills() call constructed, living in a different process).  The
worker/coordinator's own internal deadline is left at its real, normal
value. This makes the head genuinely impatient while the coordinator is
still genuinely, honestly working - no agent's behavior is faked, only
the head's patience threshold, and that's done openly via the same
reply_slack/coordinate_timeout knobs the rest of this codebase already
uses, not a special test-only code path.

Because this depends on real wall-clock timing (is the head's shrunk
window shorter than how long the real distributed round trip actually
takes this run), it's inherently less deterministic than the rest of this
suite - not something to promote to the default CI-style suite as a hard
pass/fail. Run manually to observe real behavior; reports what actually
happened either way rather than asserting a single required outcome.
"""
import os
import statistics
import threading

import pytest

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.dialogue import AgentDialogue
from scarlet_agentic_harness.llm.client import LLMClient
from scarlet_agentic_harness.skills.registry import discover_skills
from scarlet_agentic_harness import head as head_mod
from tests.helpers import WORKER_DATA, spawn_worker, terminate_all, wait_for_workers
from tests.transcript import write_transcript

pytestmark = pytest.mark.skipif(
    not os.environ.get("LLM_BASE_URL"),
    reason="requires a real LLM backend - set LLM_BASE_URL/LLM_API_KEY/LLM_MODEL to run",
)

APP_ID = "realllm_stuck"


class RecordingLLMClient:
    """Wraps a real LLMClient, recording every prompt/reply pair - used
    here to capture the deliberation call's own exchange, which (unlike
    the check-in itself) never touches the bus and so capture_transcript()
    can't see it on its own."""

    def __init__(self, inner):
        self._inner = inner
        self.calls: list[tuple[list[dict], dict]] = []

    def chat(self, messages, tools=None):
        result = self._inner.chat(messages, tools=tools)
        self.calls.append((messages, result))
        return result


def test_real_stuck_coordinator_triggers_a_real_checkin_and_deliberation(redis_conn_info):
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
        # Properly configurable now (router.py/buses.py/config.py) - no
        # more reaching into a router's private _watcher attribute. This
        # is what actually lets the artificially tiny coordinate_timeout
        # below be noticed promptly instead of waiting for the *default*
        # 0.5s scan interval, which is what silently defeated this test's
        # first two attempts.
        timeout_scan_interval=0.01,
    )
    bus_names = {"global": head_config.head_bus, "local": head_config.device_group}

    # Real workers get real LLM access too - LLM_BASE_URL/KEY/MODEL are
    # already in base_env, so __main__.py's worker branch will construct a
    # real AgentDialogue for whichever one becomes coordinator, grounded in
    # its own real CancellationRegistry - exactly as it would in real use,
    # nothing test-specific added on the worker side.
    procs = [spawn_worker(node, nums, base_env, app_id=APP_ID) for node, nums in WORKER_DATA.items()]
    result_holder: dict = {}
    deliberation_client = None
    try:
        head_buses = Buses(head_config)
        skills = discover_skills()
        median_skill = skills["median"]

        wait_for_workers(head_buses, procs, "median", expected_count=3)

        # The trick: shrink only THIS process's copy of the timeout - the
        # worker subprocess's own MedianSkill instance is untouched.
        # (First attempt at this used 0.05s and the real distributed round
        # trip still beat it - local subprocess + Redis round trips can be
        # faster than expected. Tightened further here.)
        median_skill.coordinate_timeout = 0.001

        head_dialogue = AgentDialogue(head_buses.global_bus, LLMClient(head_config))
        head_buses.global_router.default_handler = head_dialogue.handle

        deliberation_client = RecordingLLMClient(LLMClient(head_config))

        done = threading.Event()

        def on_result(result):
            result_holder["result"] = result
            done.set()

        head_mod.run_skill(
            median_skill, {}, head_config, head_buses, on_result,
            max_attempts=2, reply_slack=0.001,
            dialogue=head_dialogue, llm_client=deliberation_client,
            max_check_ins=2, check_in_timeout=30.0,
        )

        assert done.wait(timeout=60), "run_skill() never concluded"

        result = result_holder["result"]
        print("\n--- Final result ---")
        print(result)

        print(f"\n--- Deliberation calls made: {len(deliberation_client.calls)} ---")
        for i, (messages, reply) in enumerate(deliberation_client.calls, 1):
            print(f"\nDeliberation call {i} prompt:\n{messages[0]['content']}")
            print(f"\nDeliberation call {i} decision: {reply.get('content')}")

        all_numbers = [n for nums in WORKER_DATA.values() for n in nums]
        expected = statistics.median(all_numbers)
        if result.get("status") == "ok":
            assert result["result"] == expected
            print(f"\nComputation succeeded with the correct median ({expected}).")
        else:
            print(f"\nComputation did not succeed: {result}")
    finally:
        terminate_all(procs)
        llm_messages = None
        if deliberation_client is not None and deliberation_client.calls:
            llm_messages = []
            for messages, reply in deliberation_client.calls:
                llm_messages.append(messages[0])
                llm_messages.append({"role": "assistant", "content": reply.get("content"), "tool_calls": []})
        path = write_transcript(
            "test_real_stuck_coordinator_triggers_a_real_checkin_and_deliberation",
            bus_names,
            llm_messages=llm_messages,
            extra_notes=(
                f"Model: {os.environ.get('LLM_MODEL')}\n"
                f"Head-side coordinate_timeout was deliberately shrunk to 0.05s (worker's own real "
                f"internal timeout was untouched) - this is what forces the head to check in on a "
                f"genuinely still-working, unmodified real coordinator.\n"
                f"Deliberation calls made: {len(deliberation_client.calls) if deliberation_client else 0}\n"
                f"Final result: {result_holder.get('result')}"
            ),
        )
        print(f"\nTranscript written to {path}")
