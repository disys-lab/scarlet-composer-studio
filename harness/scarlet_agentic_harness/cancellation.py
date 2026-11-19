"""Re-exports the cancellation types; see cancellation_token / _registry."""
from scarlet_agentic_harness.cancellation_token import CancellationToken
from scarlet_agentic_harness.cancellation_registry import CancellationRegistry

__all__ = ["CancellationToken", "CancellationRegistry", "describe_in_flight"]

def describe_in_flight(snapshot: dict) -> str:
    """
    Format `CancellationRegistry.snapshot`'s output into explicit, unambiguous sentences.

    Not a raw dict/JSON dump - for use in an LLM prompt (see
    ``__main__.py``'s worker ``context_fn``, `dialogue`'s
    ``_system_prompt``). Found via a real-LLM test: a bare list of
    request ids left a coordinator with nothing concrete to reason from,
    so it hedged instead of answering directly. Real numbers - elapsed
    time, ready-vs-expected counts, when a skill reports them (see
    `HarnessContext.report_progress`) - let it answer specifically
    instead.

    Parameters
    ----------
    snapshot : dict
        As returned by `CancellationRegistry.snapshot`.

    Returns
    -------
    str
        One sentence per in-flight request, or a fixed "nothing in
        flight" sentence if `snapshot` is empty.
    """
    if not snapshot:
        return "Nothing currently in flight - no requests being coordinated or contributed to right now."
    lines = []
    for request_id, info in snapshot.items():
        skill = info.get("skill") or "an unnamed skill"
        elapsed = info.get("elapsed_seconds")
        elapsed_str = f"started {elapsed}s ago" if elapsed is not None else "start time unknown"
        ready = info.get("ready_count")
        expected = info.get("expected_count")
        if ready is not None and expected is not None:
            remaining = expected - ready
            progress_str = (
                f"{ready} of {expected} contributors have checked in, {remaining} still pending"
                if remaining > 0 else f"all {expected} of {expected} contributors have checked in"
            )
        else:
            progress_str = "no contributor progress reported yet"
        lines.append(f"- Request {request_id}: coordinating {skill!r}, {elapsed_str}, {progress_str}.")
    return "\n".join(lines)

