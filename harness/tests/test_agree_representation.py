"""Tests for scarlet_agentic_harness.skills.agree_representation.

These tests run without Docker or Redis. They stub the bus, router, and
dialogue to exercise the skill's agreement logic directly. The dialogue
stub is critical: AgentDialogue calls on_reply(content, sender) with the
reply TEXT first and the peer ID second. Tests verify this exact order
to prevent argument inversion bugs.

The tests cover:
1. Intersection of multiple workers' column sets
2. Single worker returns its own columns
3. Identical sets return the set
4. AGREE replies are not objections (regression guard for arg inversion)
5. Non-AGREE replies become objections keyed by agent ID
6. Objections don't fail the round; intersection still wins
7. Empty intersection is a non-retryable error with detailed message
8. No responses yields a retryable error
9. Missing dialogue still produces intersection (LLM-less fleet)
10. Empty column list participates (not skipped) and drives empty intersection
11. Replied/expected counts and coordinator doesn't dialogue with itself
"""
import threading

import pytest

from scarlet_agentic_harness.skills.agree_representation import AgreeRepresentationSkill



class Router:
    """Stub router that returns proposals in order."""

    def __init__(self, proposals):
        self.sent = list(proposals.items())

    def receive_for(self, rid, timeout=1):
        if not self.sent:
            return None
        who, cols = self.sent.pop(0)
        return {
            "body": {
                "type": "representation_proposal",
                "request_id": rid,
                "from": who,
                "columns": cols,
                "rows": 10,
            }
        }

    def forget(self, rid):
        pass


class Dialogue:
    """Stub dialogue that calls on_reply(content, sender) as the real AgentDialogue does."""

    def __init__(self, replies):
        self.replies = replies

    def start(self, peer, message, on_reply, context=None):
        # THE REAL CONTRACT: (content, sender) - text first, peer id second
        threading.Thread(target=on_reply, args=(self.replies.get(peer, ""), peer), daemon=True).start()
        return "conv-" + peer


class Cancelled:
    """Stub for cancellation flag."""

    def is_set(self):
        return False


class Ctx:
    """Context stub parameterized by test."""

    agent_id = "w1"

    def __init__(self, agent_id="w1", dialogue=None, cancelled=None, proposals=None, replies=None):
        self.agent_id = agent_id
        self.dialogue = dialogue
        self.cancelled = cancelled or Cancelled()
        self.data_profiles = {}
        self._proposals = proposals or {}
        self._replies = replies or {}

    def report_progress(self, **kw):
        pass

    class buses:
        class local_router:
            @staticmethod
            def Send(*a, **k):
                pass

        class local_bus:
            @staticmethod
            def Send(*a, **k):
                pass


def make_skill():
    """Create a fresh skill instance with short timeouts for fast tests."""
    skill = AgreeRepresentationSkill()
    skill.coordinate_timeout = 2.0
    skill.discussion_timeout = 2.0
    return skill


def test_intersection_of_multiple_workers():
    """Workers offering [a,b,c,d], [a,b,c] and [a,c,z] agree on [a,c], sorted."""
    proposals = {
        "w1": ["a", "b", "c", "d"],
        "w2": ["a", "b", "c"],
        "w3": ["a", "c", "z"],
    }
    replies = {"w2": "AGREE", "w3": "AGREE"}

    skill = make_skill()
    ctx = Ctx(agent_id="w1", proposals=proposals, replies=replies)
    ctx.buses.local_router = Router(proposals)
    ctx.dialogue = Dialogue(replies)

    res = skill.coordinate(
        ctx, {"request_id": "r1", "params": {}}, ["w1", "w2", "w3"]
    )

    assert res["status"] == "ok"
    assert res["result"] == ["a", "c"]
    assert res["objections"] == {}


def test_single_worker_returns_its_columns():
    """A single worker's columns are returned unchanged (intersection of one)."""
    proposals = {"w1": ["x", "y", "z"]}
    replies = {}

    skill = make_skill()
    ctx = Ctx(agent_id="w1", proposals=proposals, replies=replies)
    ctx.buses.local_router = Router(proposals)
    ctx.dialogue = Dialogue(replies)

    res = skill.coordinate(ctx, {"request_id": "r1", "params": {}}, ["w1"])

    assert res["status"] == "ok"
    assert res["result"] == ["x", "y", "z"]
    assert res["objections"] == {}


def test_identical_column_sets_return_that_set():
    """Identical column sets return that set."""
    proposals = {
        "w1": ["a", "b", "c"],
        "w2": ["a", "b", "c"],
        "w3": ["a", "b", "c"],
    }
    replies = {"w2": "AGREE", "w3": "AGREE"}

    skill = make_skill()
    ctx = Ctx(agent_id="w1", proposals=proposals, replies=replies)
    ctx.buses.local_router = Router(proposals)
    ctx.dialogue = Dialogue(replies)

    res = skill.coordinate(
        ctx, {"request_id": "r1", "params": {}}, ["w1", "w2", "w3"]
    )

    assert res["status"] == "ok"
    assert res["result"] == ["a", "b", "c"]
    assert res["objections"] == {}


def test_agree_replies_are_not_objections():
    """AGREE replies are not objections. Regression guard for argument inversion."""
    proposals = {
        "w1": ["a", "b", "c", "d"],
        "w2": ["a", "b", "c"],
        "w3": ["a", "c", "z"],
    }
    # Use the real reply format: text first, peer second
    replies = {"w2": "AGREE, those work for me", "w3": "AGREE"}

    skill = make_skill()
    ctx = Ctx(agent_id="w1", proposals=proposals, replies=replies)
    ctx.buses.local_router = Router(proposals)
    ctx.dialogue = Dialogue(replies)

    res = skill.coordinate(
        ctx, {"request_id": "r1", "params": {}}, ["w1", "w2", "w3"]
    )

    assert res["status"] == "ok"
    assert res["objections"] == {}, "AGREE replies must not be objections"


def test_non_agree_reply_is_recorded_as_objection():
    """A non-AGREE reply IS recorded as an objection, keyed by the AGENT ID."""
    proposals = {
        "w1": ["a", "b", "c", "d"],
        "w2": ["a", "b", "c"],
        "w3": ["a", "c", "z"],
    }
    # Non-AGREE reply from w2, AGREE from w3
    replies = {"w2": "I prefer different columns", "w3": "AGREE"}

    skill = make_skill()
    ctx = Ctx(agent_id="w1", proposals=proposals, replies=replies)
    ctx.buses.local_router = Router(proposals)
    ctx.dialogue = Dialogue(replies)

    res = skill.coordinate(
        ctx, {"request_id": "r1", "params": {}}, ["w1", "w2", "w3"]
    )

    assert res["status"] == "ok"
    assert res["objections"] == {"w2": "I prefer different columns"}
    # Verify key is agent ID, value is reply text
    assert "w2" in res["objections"]
    assert res["objections"]["w2"] == "I prefer different columns"


def test_objections_do_not_fail_the_round():
    """Objections do NOT fail the round: status is still 'ok' and result is intersection."""
    proposals = {
        "w1": ["a", "b", "c", "d"],
        "w2": ["a", "b", "c"],
        "w3": ["a", "c", "z"],
    }
    replies = {"w2": "I prefer different columns", "w3": "AGREE"}

    skill = make_skill()
    ctx = Ctx(agent_id="w1", proposals=proposals, replies=replies)
    ctx.buses.local_router = Router(proposals)
    ctx.dialogue = Dialogue(replies)

    res = skill.coordinate(
        ctx, {"request_id": "r1", "params": {}}, ["w1", "w2", "w3"]
    )

    assert res["status"] == "ok"
    assert res["result"] == ["a", "c"]  # intersection still wins
    assert res["objections"] == {"w2": "I prefer different columns"}


def test_empty_intersection_is_error_with_retryable_false():
    """An EMPTY intersection is an error with retryable False, detail mentions each worker's columns."""
    proposals = {
        "w1": ["a", "b"],
        "w2": ["c", "d"],
        "w3": ["e", "f"],
    }
    replies = {"w2": "AGREE", "w3": "AGREE"}

    skill = make_skill()
    ctx = Ctx(agent_id="w1", proposals=proposals, replies=replies)
    ctx.buses.local_router = Router(proposals)
    ctx.dialogue = Dialogue(replies)

    res = skill.coordinate(
        ctx, {"request_id": "r1", "params": {}}, ["w1", "w2", "w3"]
    )

    assert res["status"] == "error"
    assert res["retryable"] is False
    # Detail must mention each worker's columns
    detail = res.get("detail", "")
    assert "w1" in detail or "a" in detail or "b" in detail
    assert "w2" in detail or "c" in detail or "d" in detail
    assert "w3" in detail or "e" in detail or "f" in detail


def test_nobody_responses_error_retryable_true():
    """
    No worker reports at all -> error, retryable.

    Distinct from "nobody replied to the discussion", which is NOT an
    error: a silent discussion still has the deterministic intersection to
    fall back on, whereas no proposals means there is nothing to intersect
    and a retry may well find the workers awake.
    """
    proposals = {}   # nothing reported - not merely nothing *replied*
    replies = {}

    skill = make_skill()
    ctx = Ctx(agent_id="w1", proposals=proposals, replies=replies)
    ctx.buses.local_router = Router(proposals)
    ctx.dialogue = Dialogue(replies)

    res = skill.coordinate(
        ctx, {"request_id": "r1", "params": {}}, ["w1", "w2", "w3"]
    )

    assert res["status"] == "error"
    assert res["retryable"] is True


def test_dialogue_none_still_produces_intersection():
    """ctx.dialogue is None -> no discussion, result is still the intersection, status ok."""
    proposals = {
        "w1": ["a", "b", "c", "d"],
        "w2": ["a", "b", "c"],
        "w3": ["a", "c", "z"],
    }

    skill = make_skill()
    ctx = Ctx(agent_id="w1", proposals=proposals, dialogue=None)
    ctx.buses.local_router = Router(proposals)

    res = skill.coordinate(
        ctx, {"request_id": "r1", "params": {}}, ["w1", "w2", "w3"]
    )

    assert res["status"] == "ok"
    assert res["result"] == ["a", "c"]


def test_empty_column_list_participates_and_drives_empty_intersection():
    """A worker reporting an empty column list participates - not silently skipped."""
    proposals = {
        "w1": ["a", "b", "c"],
        "w2": [],  # Empty column list
        "w3": ["a", "b", "c"],
    }
    replies = {"w2": "AGREE", "w3": "AGREE"}

    skill = make_skill()
    ctx = Ctx(agent_id="w1", proposals=proposals, replies=replies)
    ctx.buses.local_router = Router(proposals)
    ctx.dialogue = Dialogue(replies)

    res = skill.coordinate(
        ctx, {"request_id": "r1", "params": {}}, ["w1", "w2", "w3"]
    )

    # Empty intersection is an error
    assert res["status"] == "error"
    assert res["retryable"] is False


def test_replied_and_expected_counts_and_coordinator_not_contacted():
    """replied and expected are reported, coordinator doesn't dialogue with itself."""
    proposals = {
        "w1": ["a", "b", "c", "d"],
        "w2": ["a", "b", "c"],
        "w3": ["a", "c", "z"],
    }
    replies = {"w2": "AGREE", "w3": "AGREE"}

    skill = make_skill()
    ctx = Ctx(agent_id="w1", proposals=proposals, replies=replies)
    ctx.buses.local_router = Router(proposals)
    ctx.dialogue = Dialogue(replies)

    res = skill.coordinate(
        ctx, {"request_id": "r1", "params": {}}, ["w1", "w2", "w3"]
    )

    # `expected` is how many workers were dispatched to (3), not how many
    # peers were talked to. The coordinator does not open a dialogue with
    # itself, so only 2 of the 3 ever reply - conflating the two numbers
    # would hide a coordinator that started talking to itself.
    assert res["replied"] == 2
    assert res["expected"] == 3
