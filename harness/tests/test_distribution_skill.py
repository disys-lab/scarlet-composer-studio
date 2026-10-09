"""
Tests for the distribution skill and its scipy wrapper.

The skill turns a statistic into a probability. Its job is to be a narrow,
checkable door onto scipy.stats - so most of what matters here is what it
*refuses*, and that the numbers match values anyone can verify by hand.
"""
import pytest

from scarlet_agentic_harness.skills import distributions
from scarlet_agentic_harness.skills.core.distribution import DistributionSkill


class _Ctx:
    agent_id = "w1"


def _run(**params):
    return DistributionSkill().coordinate(_Ctx(), {"params": params}, [])


# --- the numbers, against values that can be checked by hand --------------

def test_two_sided_p_for_the_classic_z():
    """2 * norm.sf(1.96) is 0.05 - the textbook 5% two-sided threshold."""
    out = _run(dist="norm", method="sf", x=1.96)
    assert out["status"] == "ok"
    assert 2 * out["result"] == pytest.approx(0.05, abs=1e-4)


def test_chi2_critical_value_round_trips():
    """ppf and sf are inverses: the 95th percentile has 5% in the upper tail."""
    crit = _run(dist="chi2", method="ppf", x=0.95, params={"df": 1})["result"]
    assert crit == pytest.approx(3.8415, abs=1e-3)
    assert _run(dist="chi2", method="sf", x=crit,
                params={"df": 1})["result"] == pytest.approx(0.05, abs=1e-6)


def test_f_distribution_takes_two_degrees_of_freedom():
    out = _run(dist="f", method="sf", x=1.0, params={"dfn": 10, "dfd": 10})
    assert out["status"] == "ok"
    # F(10,10) is symmetric about 1 in the sense that P(F > 1) = 0.5
    assert out["result"] == pytest.approx(0.5, abs=1e-6)


def test_a_list_gives_a_result_per_column():
    """A per-column statistic must give a per-column p-value."""
    out = _run(dist="norm", method="sf", x=[0.0, 1.96])
    assert out["result"] == pytest.approx([0.5, 0.025], abs=1e-4)


def test_a_scalar_stays_a_scalar():
    out = _run(dist="norm", method="cdf", x=0.0)
    assert isinstance(out["result"], float)


# --- what it refuses ------------------------------------------------------

def test_an_unknown_distribution_is_refused_by_name():
    out = _run(dist="cauchy", method="sf", x=1.0)
    assert out["status"] == "error"
    assert out["retryable"] is False
    assert "cauchy" in out["detail"]


def test_an_unknown_method_is_refused():
    """
    Methods are looked up in a table, never getattr'd from the request -
    otherwise any attribute on the scipy object would be reachable.
    """
    out = _run(dist="norm", method="rvs", x=1.0)
    assert out["status"] == "error"
    assert "rvs" in out["detail"]


def test_a_missing_shape_parameter_names_what_is_missing():
    out = _run(dist="chi2", method="sf", x=3.84)
    assert out["status"] == "error"
    assert "df" in out["detail"]


def test_a_non_numeric_x_is_refused_rather_than_raising_inside_scipy():
    out = _run(dist="norm", method="sf", x="not a number")
    assert out["status"] == "error"
    assert "numeric" in out["detail"]


def test_a_number_sent_as_a_string_is_accepted():
    """
    The LLM emits tool arguments as JSON and routinely types a number as
    a string. Observed live: a chi-squared question sent
    x="35.40459295505072", this refused it three times, and the head gave
    up and reported a p-value it had estimated by a normal approximation
    in its own reasoning - the exact failure this skill exists to prevent.
    """
    out = _run(dist="norm", method="sf", x="1.96")
    assert out["status"] == "ok"
    assert 2 * out["result"] == pytest.approx(0.05, abs=1e-4)


def test_a_string_in_a_list_is_accepted_too():
    """A per-column statistic arrives as a list, strings and all."""
    out = _run(dist="norm", method="sf", x=["0.0", 1.96])
    assert out["result"] == pytest.approx([0.5, 0.025], abs=1e-4)


def test_a_bool_is_still_refused():
    """bool is an int subclass, so True would quietly evaluate at 1.0."""
    out = _run(dist="norm", method="sf", x=True)
    assert out["status"] == "error"
    assert "numeric" in out["detail"]


def test_missing_required_arguments_are_refused():
    assert _run(dist="norm", method="sf")["status"] == "error"
    assert _run(dist="norm", x=1.0)["status"] == "error"


def test_every_failure_is_non_retryable():
    """These are all bad requests; a retry reproduces them exactly."""
    for bad in (dict(dist="nope", method="sf", x=1.0),
                dict(dist="norm", method="nope", x=1.0),
                dict(dist="chi2", method="sf", x=1.0)):
        assert _run(**bad)["retryable"] is False


# --- the tool description has to carry what is available ------------------

def test_the_description_lists_the_distributions_and_methods():
    """
    The LLM picks this skill from its description alone, and cannot guess
    which distributions exist.
    """
    desc = DistributionSkill.description
    for name in distributions.DISTRIBUTIONS:
        assert name in desc
    assert "sf" in desc and "ppf" in desc


# --- the building blocks must not advertise hand-composition --------------

def test_building_blocks_point_at_the_dedicated_skills():
    """
    Observed: asked for a chi2 test, the head composed it from sum_core and
    combine instead of calling chi2_test, which is registered.

    The cause was in the descriptions. sum_core's ended "...enough to derive
    mean, variance, and standard deviation WITHOUT a dedicated skill for
    each", and combine's said to derive statistics by hand "instead of
    assuming a dedicated skill exists". Both predate compound skills, and
    the head picks from these strings alone.
    """
    from scarlet_agentic_harness.skills.core.sum import SumCoreSkill
    from scarlet_agentic_harness.skills.core.combine import CombineSkill

    for cls in (SumCoreSkill, CombineSkill):
        desc = cls.description
        assert "BUILDING BLOCK" in desc, f"{cls.__name__} does not say it is low-level"
        assert "without a dedicated skill" not in desc.lower(), \
            f"{cls.__name__} still steers away from dedicated skills"
        assert "instead of assuming a dedicated skill" not in desc.lower(), \
            f"{cls.__name__} still steers away from dedicated skills"
        # and it must name at least a couple of the skills to prefer
        assert sum(n in desc for n in ("mean", "variance", "z_test", "chi2_test")) >= 3
