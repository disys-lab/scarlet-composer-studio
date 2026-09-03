"""
Unit tests for HarnessContext.report_progress() - no Redis, no subprocess.
"""
from scarlet_agentic_harness.cancellation import CancellationToken
from scarlet_agentic_harness.context import HarnessContext


def test_report_progress_delegates_to_a_real_token():
    token = CancellationToken(skill_name="median")
    ctx = HarnessContext(config=None, buses=None, cancellation=token)
    ctx.report_progress(ready_count=1, expected_count=3)
    assert token.progress_snapshot() == {"ready_count": 1, "expected_count": 3}


def test_report_progress_is_a_noop_without_a_token():
    ctx = HarnessContext(config=None, buses=None)  # no cancellation given
    ctx.report_progress(ready_count=1, expected_count=3)  # must not raise
