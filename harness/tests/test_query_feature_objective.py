"""
query_feature's objective form.

Until this sprint both `source_name` and `query_payload` were required, so
on this path the head picked the source AND wrote the SQL - the thing the
previous sprint's objective said must stop. The named form is unchanged and
is covered here as a regression guard, because notebook 11 uses it.
"""
import pytest

from scarlet_agentic_harness import local_config, local_matrix, data_profile
from scarlet_agentic_harness.skills.core.query_feature import QueryFeatureSkill


class _Bus:
    def __init__(self): self.sent = []
    def Send(self, target, body): self.sent.append(body)


class _Router:
    def __init__(self, bodies=()): self._bodies = list(bodies)
    def receive_for(self, rid, timeout=1):
        return {"body": self._bodies.pop(0)} if self._bodies else None
    def forget(self, rid): pass


class _Ctx:
    def __init__(self, agent_id="w1", router=None):
        self.agent_id = agent_id
        class _Buses:
            local_bus = _Bus()
            local_router = router or _Router()
        self.buses = _Buses()
        self.data_profiles = {"src_a": {"numeric_columns": ["x"], "rows": 3, "shape": [3, 1]}}
        self.cancelled = type("C", (), {"is_set": staticmethod(lambda: False)})()
        self.llm_client = None
    def report_progress(self, **kw): pass


def _req(**params):
    return {"request_id": "r1", "coordinator": "w1", "params": params}


def test_the_named_form_still_self_filters(monkeypatch):
    """A worker without that source sends nothing - unchanged behaviour."""
    monkeypatch.setattr(local_config, "find_source", lambda n: None)
    ctx = _Ctx()
    QueryFeatureSkill().contribute(ctx, _req(source_name="not_mine",
                                             query_payload={"query": "SELECT 1 FROM data"}))
    assert ctx.buses.local_bus.sent == []


def test_the_objective_form_picks_a_source_and_writes_its_own_sql(monkeypatch):
    """The head named nothing; the worker resolves both locally."""
    monkeypatch.setattr(data_profile, "refresh_if_stale", lambda p: False)
    monkeypatch.setattr(local_matrix, "choose_source", lambda ctx, obj: "src_a")
    monkeypatch.setattr(local_matrix, "generate_sql",
                        lambda ctx, name, obj: 'SELECT x FROM data')
    monkeypatch.setattr(local_config, "find_source",
                        lambda n: {"name": "src_a", "type": "csv", "mode": "local"})
    monkeypatch.setattr(local_config, "build_connector",
                        lambda e: type("C", (), {"query": staticmethod(
                            lambda p: {"columns": ["x"], "rows": [[1]]})})())
    ctx = _Ctx()
    QueryFeatureSkill().contribute(ctx, _req(objective="anything numeric"))
    assert len(ctx.buses.local_bus.sent) == 1
    sent = ctx.buses.local_bus.sent[0]
    assert sent["status"] == "ok"
    assert sent["source_name"] == "src_a", "the answer must say which source it used"


def test_a_worker_with_nothing_to_offer_stays_silent(monkeypatch):
    monkeypatch.setattr(data_profile, "refresh_if_stale", lambda p: False)
    monkeypatch.setattr(local_matrix, "choose_source", lambda ctx, obj: None)
    ctx = _Ctx()
    QueryFeatureSkill().contribute(ctx, _req(objective="anything"))
    assert ctx.buses.local_bus.sent == []


def test_a_failed_sql_generation_is_reported_not_swallowed(monkeypatch):
    """Silence would be indistinguishable from 'I have nothing'."""
    monkeypatch.setattr(data_profile, "refresh_if_stale", lambda p: False)
    monkeypatch.setattr(local_matrix, "choose_source", lambda ctx, obj: "src_a")
    monkeypatch.setattr(local_config, "find_source", lambda n: {"name": "src_a", "mode": "local"})
    def boom(ctx, name, obj): raise ValueError("no LLM backend")
    monkeypatch.setattr(local_matrix, "generate_sql", boom)
    ctx = _Ctx()
    QueryFeatureSkill().contribute(ctx, _req(objective="anything"))
    assert len(ctx.buses.local_bus.sent) == 1
    assert ctx.buses.local_bus.sent[0]["status"] == "error"
    assert "no LLM backend" in ctx.buses.local_bus.sent[0]["payload"]


def test_objective_form_collects_every_responder():
    """
    'Whoever has something matching this' has no single right answer, so
    the first reply must not win the way it does for a named source.
    """
    bodies = [
        {"type": "query_feature_result", "from": "w1", "source_name": "a",
         "status": "ok", "payload": {"rows": [[1]]}},
        {"type": "query_feature_result", "from": "w2", "source_name": "b",
         "status": "ok", "payload": {"rows": [[2]]}},
    ]
    skill = QueryFeatureSkill(); skill.coordinate_timeout = 2.0
    res = skill.coordinate(_Ctx(router=_Router(bodies)), _req(objective="x"), ["w1", "w2"])
    assert res["status"] == "ok"
    assert set(res["result"]) == {"w1", "w2"}
    assert res["result"]["w2"]["source"] == "b"


def test_named_form_still_returns_the_single_answer():
    bodies = [{"type": "query_feature_result", "from": "w3", "source_name": "a",
               "status": "ok", "payload": {"rows": [[9]]}}]
    skill = QueryFeatureSkill(); skill.coordinate_timeout = 2.0
    res = skill.coordinate(_Ctx(router=_Router(bodies)),
                           _req(source_name="a", query_payload={"query": "SELECT 1 FROM data"}),
                           ["w3"])
    assert res["result"] == {"rows": [[9]]}, "named form returns the payload, not a dict of workers"


# --- row filtering ----------------------------------------------------------
#
# query_feature can only honour a filter on SQL it wrote itself. The two
# cases it cannot honour are refused rather than ignored: silently dropping
# the filter hands back the unfiltered answer, which is a plausible number
# and not an error.

_WINDOW = [{"column": "ts", "op": "gte", "value": "2026-01-01T00:00:00"}]

_PROFILE = {
    "columns": [
        {"name": "x", "numeric": True, "temporal": False},
        {"name": "ts", "numeric": False, "temporal": True},
    ],
    "numeric_columns": ["x"],
    "temporal_columns": ["ts"],
    "rows": 3,
}


def _filterable_ctx():
    ctx = _Ctx()
    ctx.data_profiles = {"src_a": _PROFILE}
    return ctx


def test_the_objective_form_appends_the_filter_to_its_own_sql(monkeypatch):
    """The one path where a filter can be applied safely."""
    monkeypatch.setattr(data_profile, "refresh_if_stale", lambda p: False)
    monkeypatch.setattr(local_matrix, "choose_source", lambda ctx, obj: "src_a")
    monkeypatch.setattr(local_matrix, "generate_sql",
                        lambda ctx, src, obj: 'SELECT "x" FROM data')
    monkeypatch.setattr(local_config, "find_source",
                        lambda n: {"name": "src_a", "mode": "local", "type": "csv"})

    captured = {}

    class _Conn:
        def query(self, payload):
            captured.update(payload)
            return {"columns": ["x"], "rows": [[1.0]]}

    monkeypatch.setattr(local_config, "build_connector", lambda e: _Conn())

    ctx = _filterable_ctx()
    QueryFeatureSkill().contribute(
        ctx, _req(objective="readings", conditions=_WINDOW))

    assert "WHERE" in captured["query"]
    assert 'CAST("ts" AS TIMESTAMP) >=' in captured["query"]
    assert ctx.buses.local_bus.sent[0]["status"] == "ok"


def test_conditions_with_a_caller_supplied_query_are_refused(monkeypatch):
    """
    Refused, not ignored, and not silent.

    Silence is this skill's "not mine" signal, so a refusal that sent
    nothing would be read as absence. It has to come back as an error.
    """
    monkeypatch.setattr(local_config, "find_source",
                        lambda n: {"name": "src_a", "mode": "local", "type": "csv"})
    ctx = _filterable_ctx()
    QueryFeatureSkill().contribute(ctx, _req(
        source_name="src_a",
        query_payload={"query": 'SELECT "x" FROM data'},
        conditions=_WINDOW))

    assert len(ctx.buses.local_bus.sent) == 1, "a refusal must not be silent"
    sent = ctx.buses.local_bus.sent[0]
    assert sent["status"] == "error"
    assert "query_payload" in sent["payload"]


def test_conditions_against_a_broker_source_are_refused(monkeypatch):
    """No local profile means no way to check the filter's column exists."""
    monkeypatch.setattr(data_profile, "refresh_if_stale", lambda p: False)
    monkeypatch.setattr(local_matrix, "choose_source", lambda ctx, obj: "src_a")
    monkeypatch.setattr(local_matrix, "generate_sql",
                        lambda ctx, src, obj: 'SELECT "x" FROM data')
    monkeypatch.setattr(local_config, "find_source",
                        lambda n: {"name": "src_a", "mode": "broker"})

    ctx = _filterable_ctx()
    QueryFeatureSkill().contribute(
        ctx, _req(objective="readings", conditions=_WINDOW))

    sent = ctx.buses.local_bus.sent[-1]
    assert sent["status"] == "error"
    assert "broker" in sent["payload"]


def test_no_conditions_leaves_the_objective_form_untouched(monkeypatch):
    """Regression guard: the unfiltered path emits no WHERE."""
    monkeypatch.setattr(data_profile, "refresh_if_stale", lambda p: False)
    monkeypatch.setattr(local_matrix, "choose_source", lambda ctx, obj: "src_a")
    monkeypatch.setattr(local_matrix, "generate_sql",
                        lambda ctx, src, obj: 'SELECT "x" FROM data')
    monkeypatch.setattr(local_config, "find_source",
                        lambda n: {"name": "src_a", "mode": "local", "type": "csv"})

    captured = {}

    class _Conn:
        def query(self, payload):
            captured.update(payload)
            return {"columns": ["x"], "rows": [[1.0]]}

    monkeypatch.setattr(local_config, "build_connector", lambda e: _Conn())

    ctx = _filterable_ctx()
    QueryFeatureSkill().contribute(ctx, _req(objective="readings"))
    assert "WHERE" not in captured["query"]
