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


def test_default_coordinator_is_self():
    """A hypothetical Federator-style skill (default coordinator_for) should
    pick the head itself - only MedianSkill overrides this."""

    class _FakeCtx:
        agent_id = "head_x"

    class _Dummy(Skill):
        name = "dummy"
        description = "unused"

        def contribute(self, ctx, request):
            pass

        def coordinate(self, ctx, request, workers):
            pass

    assert _Dummy().coordinator_for(_FakeCtx(), ["w1", "w2"]) == "head_x"
