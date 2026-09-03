"""
Tests head.run_skill()'s deliberation path (dialogue/llm_client params) -
a timeout no longer means an immediate mechanical retry when both are
supplied: it means a real check-in conversation with the coordinator
(AgentDialogue), a small LLM call weighing the reply, and only then either
re-arming the original wait (WAIT) or proceeding with the existing
cancel-and-retry logic (RETRY).

Same fake-worker-via-raw-Messenger-traffic pattern as
test_run_skill_retry.py, extended with a real AgentDialogue on the fake
worker's side (so it can receive and answer the head's check-in) and a
separate scripted LLM standing in for run_skill()'s own deliberation call
(a different call than whatever the fake coordinator's own dialogue LLM
does to formulate its reply).
"""
import os
import threading

from scarlet_agentic_harness import head as head_mod
from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.dialogue import AgentDialogue
from scarlet_agentic_harness.skills.base import Skill
from tests.helpers import APP_ID


def _stop(buses: Buses) -> None:
    buses.global_router.stop()
    buses.local_router.stop()


class _StubSkill(Skill):
    """Test-only, same shape as test_run_skill_retry.py's - no real
    computation, a fake worker answers on its behalf. coordinate_timeout
    is much more generous here than in test_run_skill_retry.py: these
    tests have real extra work happening in the window (a check-in
    conversation, a Timer, spawned threads) that a plain timeout test
    doesn't, and a too-tight window causes a second, spurious timeout
    before a re-armed wait even has a chance - that's a test-timing
    concern, not something about the underlying logic being tested."""
    description = "test-only"
    coordinate_timeout = 2.0

    def __init__(self, name: str):
        self.name = name

    def contribute(self, ctx, request):
        raise AssertionError("never called - no real worker in this test")

    def coordinate(self, ctx, request, workers):
        raise AssertionError("never called on the head - a fake worker replies instead")

    def coordinator_for(self, ctx, workers):
        return workers[0]


class ScriptedChatClient:
    """Records every call, returns pre-scripted replies in order - used
    both for run_skill()'s deliberation call and the fake coordinator's
    own AgentDialogue reply generation (two independent instances per
    test, standing in for two different LLM calls). on_call, if given,
    fires synchronously as part of chat() itself - a precise, immediate
    signal that this call happened, rather than a test having to poll for
    it afterward."""

    def __init__(self, replies: list[str], on_call=None):
        self._replies = list(replies)
        self.calls: list[list[dict]] = []
        self._on_call = on_call

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        self.calls.append(messages)
        content = self._replies.pop(0)
        if self._on_call is not None:
            self._on_call()
        return {"role": "assistant", "content": content, "tool_calls": []}


def _setup(redis_conn_info, suffix: str):
    base_env = dict(os.environ)
    base_env.update({
        "REDIS_HOST": redis_conn_info["host"],
        "REDIS_PORT": redis_conn_info["port"],
        "REDIS_AUTH_TOKEN": redis_conn_info["auth_token"],
    })
    os.environ.update(base_env)

    head_config = HarnessConfig(
        role="head", app_id=APP_ID, node_address=f"head-deliberate-{suffix}",
        device_group=f"{APP_ID}_subagent", head_bus=f"{APP_ID}_headagent",
        llm_base_url=None, llm_api_key=None, llm_model=None,
    )
    head_buses = Buses(head_config)

    fake_worker_config = HarnessConfig(
        role="worker", app_id=APP_ID, node_address=f"fakeworker-deliberate-{suffix}",
        device_group=f"{APP_ID}_subagent", head_bus=f"{APP_ID}_headagent",
        llm_base_url=None, llm_api_key=None, llm_model=None,
    )
    fake_worker_buses = Buses(fake_worker_config)
    fake_worker_buses.report_status(capabilities=[f"stub_deliberate_{suffix}"])

    return head_config, head_buses, fake_worker_config, fake_worker_buses


def test_wait_decision_lets_a_late_real_result_still_succeed(redis_conn_info):
    head_config, head_buses, fake_worker_config, fake_worker_buses = _setup(redis_conn_info, "wait")

    coordinate_seen: list[str] = []
    checkin_answered = threading.Event()

    worker_dialogue = AgentDialogue(
        fake_worker_buses.global_bus,
        ScriptedChatClient(
            ["still working, almost done - one contributor is just slow"],
            on_call=checkin_answered.set,
        ),
    )

    def fake_worker_handler(msg: dict) -> None:
        body = msg.get("body", {})
        msg_type = body.get("type")
        if msg_type == "skill_coordinate":
            coordinate_seen.append(body["request_id"])
            # Deliberately never replies with a real skill_result here -
            # the test sends one manually, later, once it's confirmed the
            # check-in round-trip actually happened.
        elif msg_type == "agent_message":
            worker_dialogue.handle(msg)

    fake_worker_buses.global_router.default_handler = fake_worker_handler

    head_dialogue = AgentDialogue(head_buses.global_bus, ScriptedChatClient([]))  # never called - head only initiates here
    # Without this, the coordinator's reply to the check-in arrives on the
    # global bus as an unkeyed agent_message (see buses.py's
    # _global_bus_key) and is silently dropped instead of reaching
    # head_dialogue's registered reply handler - real __main__.py wires
    # this the same way for the head's LLM-backed chat mode.
    head_buses.global_router.default_handler = head_dialogue.handle
    # Two calls per check-in now: the opening question is itself composed
    # by an LLM call (_compose_checkin_question), then a second call
    # weighs the coordinator's reply (_deliberate_or_followup).
    deliberation_llm = ScriptedChatClient(["how's the median coming along?", "WAIT"])

    try:
        skill = _StubSkill("stub_deliberate_wait")
        result_box: dict = {}
        done = threading.Event()

        def on_result(result):
            result_box["result"] = result
            done.set()

        head_mod.run_skill(
            skill, {}, head_config, head_buses, on_result,
            max_attempts=2, reply_slack=2.0,
            dialogue=head_dialogue, llm_client=deliberation_llm,
            max_check_ins=2, check_in_timeout=3.0,
        )

        # Confirm the check-in was actually sent, received, and answered
        # by the fake coordinator before doing anything else - checkin_answered
        # fires synchronously inside the fake coordinator's chat() call, so
        # this is a precise signal, not a poll with its own race window.
        assert checkin_answered.wait(timeout=5), "check-in was never answered"

        assert not done.is_set(), "run_skill() concluded before the late real result was sent - WAIT didn't re-arm"

        fake_worker_buses.global_bus.Send(head_config.agent_id, {
            "type": "skill_result", "request_id": coordinate_seen[0], "status": "ok", "result": 42,
        })

        assert done.wait(timeout=5)
        assert result_box["result"]["status"] == "ok"
        assert result_box["result"]["result"] == 42
        assert len(coordinate_seen) == 1  # no retry happened - WAIT means no new attempt
        assert len(deliberation_llm.calls) == 2  # compose the opening question, then decide
    finally:
        _stop(head_buses)
        _stop(fake_worker_buses)


def test_retry_decision_proceeds_with_normal_retry(redis_conn_info):
    head_config, head_buses, fake_worker_config, fake_worker_buses = _setup(redis_conn_info, "retry")

    coordinate_seen: list[str] = []
    cancels_seen: list[str] = []

    worker_dialogue = AgentDialogue(
        fake_worker_buses.global_bus,
        ScriptedChatClient(["honestly this looks stuck, no contributors have checked in at all"]),
    )

    def fake_worker_handler(msg: dict) -> None:
        body = msg.get("body", {})
        msg_type = body.get("type")
        if msg_type == "skill_coordinate":
            coordinate_seen.append(body["request_id"])
            if len(coordinate_seen) >= 2:
                # Second attempt (after the retry) answers normally.
                fake_worker_buses.global_bus.Send(msg["from"], {
                    "type": "skill_result", "request_id": body["request_id"], "status": "ok", "result": 7,
                })
        elif msg_type == "agent_message":
            worker_dialogue.handle(msg)
        elif msg_type == "skill_cancel":
            cancels_seen.append(body["request_id"])

    fake_worker_buses.global_router.default_handler = fake_worker_handler

    head_dialogue = AgentDialogue(head_buses.global_bus, ScriptedChatClient([]))
    head_buses.global_router.default_handler = head_dialogue.handle
    deliberation_llm = ScriptedChatClient(["how's the median coming along?", "RETRY"])

    try:
        skill = _StubSkill("stub_deliberate_retry")
        result_box: dict = {}
        done = threading.Event()

        def on_result(result):
            result_box["result"] = result
            done.set()

        head_mod.run_skill(
            skill, {}, head_config, head_buses, on_result,
            max_attempts=2, reply_slack=0.5,
            dialogue=head_dialogue, llm_client=deliberation_llm,
            max_check_ins=2, check_in_timeout=3.0,
        )

        assert done.wait(timeout=8)
        assert result_box["result"]["status"] == "ok"
        assert result_box["result"]["result"] == 7
        assert len(coordinate_seen) == 2  # the retry actually happened
        assert cancels_seen == [coordinate_seen[0]]  # first attempt cancelled, not the second
        assert len(deliberation_llm.calls) == 2  # compose the opening question, then decide
    finally:
        _stop(head_buses)
        _stop(fake_worker_buses)


def test_followup_question_continues_the_checkin_conversation_before_deciding(redis_conn_info):
    """A live model may or may not choose to ask a follow-up on any given
    run (see tests/test_real_llm_stuck_and_checkin.py's transcripts for
    real examples) - this scripts one deterministically, proving the
    mechanism itself (dialogue.reply() re-entering on_checkin_reply,
    growing the same transcript, both sides seeing the real conversation
    so far) actually works, independent of whether any particular real
    run happens to exercise it."""
    head_config, head_buses, fake_worker_config, fake_worker_buses = _setup(redis_conn_info, "followup")

    coordinate_seen: list[str] = []
    replies_received: list[str] = []
    both_rounds_answered = threading.Event()

    worker_dialogue = AgentDialogue(
        fake_worker_buses.global_bus,
        ScriptedChatClient([
            "still working on it, one contributor hasn't checked in yet",
            "it's the second worker - haven't heard from it in a while",
        ]),
    )

    def fake_worker_handler(msg: dict) -> None:
        body = msg.get("body", {})
        msg_type = body.get("type")
        if msg_type == "skill_coordinate":
            coordinate_seen.append(body["request_id"])
        elif msg_type == "agent_message":
            replies_received.append(body.get("content"))
            worker_dialogue.handle(msg)
            if len(replies_received) >= 2:
                both_rounds_answered.set()

    fake_worker_buses.global_router.default_handler = fake_worker_handler

    head_dialogue = AgentDialogue(head_buses.global_bus, ScriptedChatClient([]))
    head_buses.global_router.default_handler = head_dialogue.handle
    deliberation_llm = ScriptedChatClient([
        "how's the median coming along?",
        "ASK: which contributor specifically hasn't checked in?",
        "WAIT",
    ])

    try:
        skill = _StubSkill("stub_deliberate_followup")
        result_box: dict = {}
        done = threading.Event()

        def on_result(result):
            result_box["result"] = result
            done.set()

        head_mod.run_skill(
            skill, {}, head_config, head_buses, on_result,
            max_attempts=2, reply_slack=2.0,
            dialogue=head_dialogue, llm_client=deliberation_llm,
            max_check_ins=2, check_in_timeout=5.0, check_in_max_turns=3,
        )

        assert both_rounds_answered.wait(timeout=5), "the follow-up round never reached the coordinator"
        assert len(replies_received) == 2  # the opening question, then a genuine follow-up - not one fixed exchange
        assert not done.is_set(), "run_skill() concluded before the late real result was sent - WAIT didn't re-arm"

        fake_worker_buses.global_bus.Send(head_config.agent_id, {
            "type": "skill_result", "request_id": coordinate_seen[0], "status": "ok", "result": 42,
        })

        assert done.wait(timeout=5)
        assert result_box["result"]["status"] == "ok"
        assert len(coordinate_seen) == 1  # WAIT (after the follow-up) means no retry happened
        assert len(deliberation_llm.calls) == 3  # compose question, decide -> ASK, decide (after follow-up) -> WAIT
    finally:
        _stop(head_buses)
        _stop(fake_worker_buses)


def test_checkin_itself_timing_out_falls_back_to_retry(redis_conn_info):
    head_config, head_buses, fake_worker_config, fake_worker_buses = _setup(redis_conn_info, "checkintimeout")

    coordinate_seen: list[str] = []

    def fake_worker_handler(msg: dict) -> None:
        body = msg.get("body", {})
        if body.get("type") == "skill_coordinate":
            coordinate_seen.append(body["request_id"])
            if len(coordinate_seen) >= 2:
                fake_worker_buses.global_bus.Send(msg["from"], {
                    "type": "skill_result", "request_id": body["request_id"], "status": "ok", "result": 3,
                })
        # agent_message deliberately ignored - the fake coordinator never
        # answers the check-in at all, forcing check_in_timeout to fire.

    fake_worker_buses.global_router.default_handler = fake_worker_handler

    head_dialogue = AgentDialogue(head_buses.global_bus, ScriptedChatClient([]))
    # One reply here, not zero: composing the opening question still happens
    # (it's what gets sent) - it's only the *deliberate* call (weighing a
    # reply) that never happens, since the check-in itself times out first
    # with no reply ever received.
    deliberation_llm = ScriptedChatClient(["how's the median coming along?"])

    try:
        skill = _StubSkill("stub_deliberate_checkintimeout")
        result_box: dict = {}
        done = threading.Event()

        def on_result(result):
            result_box["result"] = result
            done.set()

        head_mod.run_skill(
            skill, {}, head_config, head_buses, on_result,
            max_attempts=2, reply_slack=0.5,
            dialogue=head_dialogue, llm_client=deliberation_llm,
            max_check_ins=2, check_in_timeout=0.5,
        )

        assert done.wait(timeout=8)
        assert result_box["result"]["status"] == "ok"
        assert result_box["result"]["result"] == 3
        assert len(coordinate_seen) == 2
        assert len(deliberation_llm.calls) == 1  # only the opening question composition
    finally:
        _stop(head_buses)
        _stop(fake_worker_buses)
