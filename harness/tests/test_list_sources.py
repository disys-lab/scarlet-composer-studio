"""Tests for scarlet_agentic_harness.skills.core.list_sources.

These tests run without Docker or Redis. They stub the bus, router, and
context to exercise the skill's source-listing logic directly. The tests
cover redaction of paths, handling of missing profiles, shape/numeric
columns, empty source lists, stale profile refresh, merging across
workers, and error cases for missing responses.
"""
import pytest

from scarlet_agentic_harness.skills.core.list_sources import ListSourcesSkill


class Router:
    """Stub router that returns worker reports in order."""

    def __init__(self, reports):
        self.reports = list(reports.items())

    def receive_for(self, rid, timeout=1):
        if not self.reports:
            return None
        who, sources = self.reports.pop(0)
        return {
            "body": {
                "type": "source_inventory",   # must match list_sources._RESULT_MSG_TYPE
                "request_id": rid,
                "from": who,
                "sources": sources,
            }
        }

    def forget(self, rid):
        pass


class Cancelled:
    """Stub for cancellation flag."""

    def is_set(self):
        return False


class Ctx:
    """Context stub parameterized by test."""

    agent_id = "w1"

    def __init__(
        self,
        agent_id="w1",
        data_profiles=None,
        local_config_describe_sources=None,
        cancelled=None,
        reports=None,
    ):
        self.agent_id = agent_id
        self.data_profiles = data_profiles or {}
        self._describe_sources = local_config_describe_sources
        self.cancelled = cancelled or Cancelled()
        self._reports = reports or {}
        # Per-instance so tests never see another test's traffic, and
        # recording because contribute() returns None - the message it
        # Sends IS its output, and that is what must be asserted on.
        self.sent: list[tuple] = []
        outer = self

        class _Bus:
            @staticmethod
            def Send(target, body):
                outer.sent.append((target, body))

        class _Buses:
            local_bus = _Bus()
            local_router = None

        self.buses = _Buses()

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
    skill = ListSourcesSkill()
    skill.coordinate_timeout = 2.0
    skill.discussion_timeout = 2.0
    return skill


def test_path_is_redacted_from_all_source_dicts():
    """The 'path' key never appears in any source dict, and the path value never appears in the serialised message."""
    from scarlet_agentic_harness import local_config

    # Patch describe_sources to return a real path
    def fake_describe_sources():
        return [
            {
                "name": "my_table",
                "path": "/secret/path/to/my_table",
                "shape": [100, 5],
                "numeric_columns": ["col1", "col2"],
            }
        ]

    original_describe_sources = local_config.describe_sources
    local_config.describe_sources = fake_describe_sources

    try:
        skill = make_skill()
        ctx = Ctx(agent_id="w1", local_config_describe_sources=fake_describe_sources)
        ctx.buses.local_router = Router({})

        skill.contribute(ctx, {"request_id": "r1", "coordinator": "w1", "params": {}})
        assert len(ctx.sent) == 1, "contribute must Send exactly one message"
        res = ctx.sent[0][1]

        # Assert 'path' key is absent from all source dicts
        sources = res.get("sources", [])
        for src in sources:
            assert "path" not in src, f"'path' key found in source dict: {src}"

        # Assert path value is absent from the serialised message
        import json

        serialised = json.dumps(res)
        assert "/secret/path/to/my_table" not in serialised, "Path value leaked into serialised message"
    finally:
        local_config.describe_sources = original_describe_sources


def test_source_in_describe_sources_but_absent_from_profiles_reports_with_shape_none():
    """A source present in describe_sources() but absent from ctx.data_profiles is still reported, with shape None."""
    from scarlet_agentic_harness import local_config

    def fake_describe_sources():
        return [
            {"name": "my_table", "path": "/secret/path/to/my_table"},
        ]

    original_describe_sources = local_config.describe_sources
    local_config.describe_sources = fake_describe_sources

    try:
        skill = make_skill()
        ctx = Ctx(agent_id="w1", local_config_describe_sources=fake_describe_sources)
        ctx.buses.local_router = Router({})

        skill.contribute(ctx, {"request_id": "r1", "coordinator": "w1", "params": {}})
        assert len(ctx.sent) == 1, "contribute must Send exactly one message"
        res = ctx.sent[0][1]

        sources = res.get("sources", [])
        assert len(sources) == 1
        assert sources[0]["name"] == "my_table"
        assert sources[0].get("shape") is None
    finally:
        local_config.describe_sources = original_describe_sources


def test_shape_and_numeric_columns_are_carried_through_for_profiled_source():
    """shape and numeric_columns are carried through for a profiled source."""
    from scarlet_agentic_harness import local_config

    def fake_describe_sources():
        return [
            {"name": "my_table", "path": "/secret/path/to/my_table"},
        ]

    original_describe_sources = local_config.describe_sources
    local_config.describe_sources = fake_describe_sources

    try:
        skill = make_skill()
        ctx = Ctx(
            agent_id="w1",
            local_config_describe_sources=fake_describe_sources,
            data_profiles={
                "my_table": {
                    "shape": [100, 5],
                    "numeric_columns": ["col1", "col2"],
                }
            },
        )
        ctx.buses.local_router = Router({})

        skill.contribute(ctx, {"request_id": "r1", "coordinator": "w1", "params": {}})
        assert len(ctx.sent) == 1, "contribute must Send exactly one message"
        res = ctx.sent[0][1]

        sources = res.get("sources", [])
        assert len(sources) == 1
        assert sources[0]["name"] == "my_table"
        assert sources[0]["shape"] == [100, 5]
        assert sources[0]["numeric_columns"] == ["col1", "col2"]
    finally:
        local_config.describe_sources = original_describe_sources


def test_worker_with_no_sources_still_sends_message_with_empty_list():
    """A worker with no sources still Sends a message, with an empty list."""
    from scarlet_agentic_harness import local_config

    def fake_describe_sources():
        return []

    original_describe_sources = local_config.describe_sources
    local_config.describe_sources = fake_describe_sources

    try:
        skill = make_skill()
        ctx = Ctx(agent_id="w1", local_config_describe_sources=fake_describe_sources)
        ctx.buses.local_router = Router({})

        skill.contribute(ctx, {"request_id": "r1", "coordinator": "w1", "params": {}})
        assert len(ctx.sent) == 1, "contribute must Send exactly one message"
        res = ctx.sent[0][1]

        assert res.get("sources") == []
    finally:
        local_config.describe_sources = original_describe_sources


def test_data_profile_refresh_if_stale_is_called():
    """data_profile.refresh_if_stale is called. Monkeypatch it with a spy that records the call."""
    from scarlet_agentic_harness import local_config
    from scarlet_agentic_harness import data_profile

    refresh_called = []

    def fake_describe_sources():
        return []

    def fake_refresh_if_stale(*a, **k):
        refresh_called.append((a, k))
        return None

    original_describe_sources = local_config.describe_sources
    original_refresh_if_stale = data_profile.refresh_if_stale

    local_config.describe_sources = fake_describe_sources
    data_profile.refresh_if_stale = fake_refresh_if_stale

    try:
        skill = make_skill()
        ctx = Ctx(agent_id="w1", local_config_describe_sources=fake_describe_sources)
        ctx.buses.local_router = Router({})

        skill.contribute(ctx, {"request_id": "r1", "coordinator": "w1", "params": {}})
        assert len(ctx.sent) == 1, "contribute must Send exactly one message"
        res = ctx.sent[0][1]

        assert len(refresh_called) == 1, "data_profile.refresh_if_stale was not called"
    finally:
        local_config.describe_sources = original_describe_sources
        data_profile.refresh_if_stale = original_refresh_if_stale


def test_sources_from_several_workers_are_merged_under_agent_ids_and_total_sources_is_sum():
    """Sources from several workers are merged under their agent ids, and total_sources is the sum across all of them."""
    from scarlet_agentic_harness import local_config

    def fake_describe_sources():
        return []

    original_describe_sources = local_config.describe_sources
    local_config.describe_sources = fake_describe_sources

    try:
        skill = make_skill()
        ctx = Ctx(agent_id="w1", local_config_describe_sources=fake_describe_sources)
        ctx.buses.local_router = Router(
            {
                "w1": [{"name": "w1_table"}],
                "w2": [{"name": "w2_table"}, {"name": "w2_table2"}],
                "w3": [{"name": "w3_table"}],
            }
        )

        res = skill.coordinate(
            ctx, {"request_id": "r1", "coordinator": "w1", "params": {}}, ["w1", "w2", "w3"]
        )

        assert res["status"] == "ok"
        assert res["total_sources"] == 4
        assert "w1" in res["result"]
        assert "w2" in res["result"]
        assert "w3" in res["result"]
        assert len(res["result"]["w1"]) == 1
        assert len(res["result"]["w2"]) == 2
        assert len(res["result"]["w3"]) == 1
    finally:
        local_config.describe_sources = original_describe_sources


def test_responders_with_no_sources_give_status_ok_with_empty_result_and_total_sources_0():
    """Responders that hold NO sources give status 'ok' with an empty-ish result and total_sources 0."""
    from scarlet_agentic_harness import local_config

    def fake_describe_sources():
        return []

    original_describe_sources = local_config.describe_sources
    local_config.describe_sources = fake_describe_sources

    try:
        skill = make_skill()
        ctx = Ctx(agent_id="w1", local_config_describe_sources=fake_describe_sources)
        ctx.buses.local_router = Router(
            {
                "w1": [],
                "w2": [],
            }
        )

        res = skill.coordinate(ctx, {"request_id": "r1", "coordinator": "w1", "params": {}}, ["w1", "w2"])

        assert res["status"] == "ok"
        assert res["total_sources"] == 0
        # Each responder appears with an empty list, NOT an empty dict.
        # That distinction is the point: "two workers answered and hold
        # nothing" must be tellable from "nobody answered", which is the
        # retryable error case. Collapsing both to {} would lose it.
        assert res["result"] == {"w1": [], "w2": []}
    finally:
        local_config.describe_sources = original_describe_sources


def test_nobody_reports_at_all_status_error_retryable_true():
    """Nobody reports at all -> status 'error', retryable True."""
    from scarlet_agentic_harness import local_config

    def fake_describe_sources():
        return []

    original_describe_sources = local_config.describe_sources
    local_config.describe_sources = fake_describe_sources

    try:
        skill = make_skill()
        ctx = Ctx(agent_id="w1", local_config_describe_sources=fake_describe_sources)
        ctx.buses.local_router = Router({})  # no reports

        res = skill.coordinate(
            ctx, {"request_id": "r1", "coordinator": "w1", "params": {}}, ["w1", "w2", "w3"]
        )

        assert res["status"] == "error"
        assert res["retryable"] is True
    finally:
        local_config.describe_sources = original_describe_sources


def test_replied_and_expected_are_reported():
    """replied and expected are reported."""
    from scarlet_agentic_harness import local_config

    def fake_describe_sources():
        return []

    original_describe_sources = local_config.describe_sources
    local_config.describe_sources = fake_describe_sources

    try:
        skill = make_skill()
        ctx = Ctx(agent_id="w1", local_config_describe_sources=fake_describe_sources)
        ctx.buses.local_router = Router(
            {
                "w2": [{"name": "w2_table"}],
                "w3": [{"name": "w3_table"}],
            }
        )

        res = skill.coordinate(
            ctx, {"request_id": "r1", "coordinator": "w1", "params": {}}, ["w1", "w2", "w3"]
        )

        # The skill reports 'replied' and 'expected' in the result
        assert "replied" in res, "replied count must be present in result"
        assert "expected" in res, "expected count must be present in result"
        assert res["replied"] == 2
        assert res["expected"] == 3
    finally:
        local_config.describe_sources = original_describe_sources
