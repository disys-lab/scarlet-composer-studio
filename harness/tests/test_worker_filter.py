"""
The `workers` parameter on sum and median.

No Docker or Redis: contribute's self-filter and coordinate's narrowing are
both pure request/params logic. The point of these tests is that the two
narrow TOGETHER - narrowing only contribute leaves coordinate waiting on
workers that were told to stay silent, which surfaces as a readiness
timeout and reads as a hang rather than as a filter.
"""
import pytest

from scarlet_agentic_harness.skills.core.sum import SumCoreSkill as SumSkill
from scarlet_agentic_harness.skills.core.median import MedianSkill


class _Bus:
    def __init__(self): self.sent = []
    def Send(self, target, body): self.sent.append((target, body))


class _Router:
    """coordinate()'s finally calls forget() regardless of outcome."""
    def forget(self, request_id): pass
    def receive_for(self, request_id, timeout=1): return None


class _Ctx:
    def __init__(self, agent_id):
        self.agent_id = agent_id
        class _Buses:
            local_bus = _Bus()
            local_router = _Router()
        self.buses = _Buses()
        self.data_profiles = {}
        self.cancelled = type("C", (), {"is_set": staticmethod(lambda: False)})()
    def report_progress(self, **kw): pass


def _req(workers=None, **params):
    p = dict(params)
    if workers is not None:
        p["workers"] = workers
    # mapper_name is minted by run_skill and both skills read it when they
    # build their Federator/Mapper.
    return {"request_id": "r1", "coordinator": "w1", "mapper_name": "m1", "params": p}


@pytest.mark.parametrize("skill", [SumSkill(), MedianSkill()])
def test_a_worker_not_in_the_list_sends_nothing(skill):
    """Self-filter, query_feature style: silence, not a 'not applicable' signal."""
    ctx = _Ctx("w4")
    skill.contribute(ctx, _req(workers=["w1", "w2", "w3"]))
    assert ctx.buses.local_bus.sent == []


@pytest.mark.parametrize("skill", [SumSkill(), MedianSkill()])
def test_coordinate_rejects_a_worker_that_was_never_dispatched_to(skill):
    """
    Asking for an offline worker must be loud.

    Silently aggregating the three that are present returns a plausible
    number for a different question.
    """
    res = skill.coordinate(_Ctx("w1"), _req(workers=["w1", "w99"]), ["w1", "w2"])
    assert res["status"] == "error"
    assert "w99" in res["detail"]
    assert res["retryable"] is False


@pytest.mark.parametrize("skill", [SumSkill(), MedianSkill()])
def test_a_request_matching_nobody_is_its_own_error(skill):
    """Not a readiness timeout - nothing would ever arrive."""
    res = skill.coordinate(_Ctx("w1"), _req(workers=["w8", "w9"]), ["w1", "w2"])
    assert res["status"] == "error"
    assert res["retryable"] is False


@pytest.mark.parametrize("skill", [SumSkill(), MedianSkill()])
def test_omitting_workers_lets_every_worker_through(skill, monkeypatch):
    """
    The filter is opt-in. With no `workers`, contribute must proceed past the
    self-filter and actually report - otherwise adding the parameter would
    silently change behaviour for every existing caller.

    Data loading is stubbed; this is about the filter, not the connector.
    """
    import numpy as np
    from scarlet_agentic_harness import local_matrix

    monkeypatch.setattr(local_matrix, "load_local_matrix",
                        lambda ctx, objective, columns=None, conditions=None:
                            (np.array([[1.0, 2.0], [3.0, 4.0]]), {"source": "stub"}))

    class _Fed:
        def Map(self, value, key): return (None, True, None)
    class _Mapper:
        def Map(self, value, key): return (None, True, None)
    ctx = _Ctx("w4")
    ctx.federator = lambda *a, **k: _Fed()
    ctx.mapper = lambda *a, **k: _Mapper()

    skill.contribute(ctx, _req())
    assert ctx.buses.local_bus.sent, "a worker with no filter must still report"
