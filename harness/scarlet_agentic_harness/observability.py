"""
Live worker-activity observability, via a shared Mapper - not
CancellationRegistry's own request_id/CancellationToken bookkeeping,
which is in-process only and can't leave a worker's memory (see
cancellation.py). Each worker publishes its current in-flight request IDs
under its own key; AllGather() reads back a snapshot across every worker
at once.

Unlike scarlets' own agent registry (Messenger.Register()/ReportStatus() -
confirmed by reading the installed package to have no TTL at all, which is
exactly why buses.py's gather_workers() needed its own staleness filter),
Mapper values DO get an automatic TTL (scarletDataExpiry, ~1hr default) -
a worker that crashes without cleaning up doesn't leave a permanently
"busy"-looking entry behind forever, unlike the raw agent registry does.

This is purely observational - nothing about dispatch, retry, or
cancellation depends on it. It answers "what is everyone doing right now"
for a human, a dashboard, or a future check-in conversation's context_fn
(see dialogue.py, worker's construction in __main__.py) - not "is this
specific request still alive", which is what CancellationRegistry answers.
"""
from scarlets.core.Mapper import Mapper


def activity_mapper(app_id: str) -> Mapper:
    """
    Build the shared `Mapper` every agent in a campaign publishes activity to.

    Scoped consistently by `app_id` so every agent in the same campaign
    publishes to (and reads from) the same place.

    Parameters
    ----------
    app_id : str

    Returns
    -------
    Mapper
    """
    return Mapper(
        f"{app_id}_activity",
        description="Live per-agent in-flight request snapshot - see observability.py.",
    )


def snapshot(mapper: Mapper) -> dict:
    """
    Read back every agent's last-published activity.

    Parameters
    ----------
    mapper : Mapper
        As returned by `activity_mapper`.

    Returns
    -------
    dict
        Per-agent activity, keyed by agent id. `{}` on failure rather
        than raising - this is best-effort visibility, not something
        dispatch/retry/cancellation logic depends on.
    """
    gathered, status, _exc = mapper.AllGather()
    return gathered if status else {}
