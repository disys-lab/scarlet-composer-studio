"""No Redis needed - pure discovery/interface checks."""
from scarlet_agentic_harness.skills.registry import discover_skills
from scarlet_agentic_harness.skills.base import Skill


def test_discovers_median():
    skills = discover_skills()
    assert "median" in skills
    assert isinstance(skills["median"], Skill)


def test_tool_schema_shape():
    skills = discover_skills()
    schema = skills["median"].as_tool_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "median"
    assert "description" in schema["function"]
    assert "parameters" in schema["function"]


def test_default_coordinator_is_a_worker_not_the_head():
    """Skill's base default (no coordinator_for() override) should pick a
    worker, never the head - keeps the head a pure router even for skills
    that never override this, so it doesn't become a bottleneck for every
    skill's aggregation step under concurrent invocations."""

    class _FakeCtx:
        agent_id = "head_x"

    class _Dummy(Skill):
        name = "dummy"
        description = "unused"

        def contribute(self, ctx, request):
            pass

        def coordinate(self, ctx, request, workers):
            pass

    workers = ["w1", "w2", "w3"]
    for _ in range(20):  # random.choice - sample enough to catch a wrong constant pick
        picked = _Dummy().coordinator_for(_FakeCtx(), workers)
        assert picked in workers
        assert picked != "head_x"
