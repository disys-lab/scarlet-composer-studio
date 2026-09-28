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


def activity_mapper(name: str) -> Mapper:
    """
    Build the shared `Mapper` every agent in a campaign publishes activity to.

    Takes the already-resolved name (`HarnessConfig.activity_mapper`)
    rather than deriving it from `app_id` here. Deriving it made a
    campaign's scope a function of `app_id`, which is not always the
    deployer's to choose: Gustavo overwrites ``APP_ID`` with the app's own
    name (see ``gustavo/api/routers/apps.py``), so a fleet split across
    several Gustavo apps got one mapper per app rather than one per
    campaign, with no way to override it. `HarnessConfig` still falls back
    to ``f"{app_id}_activity"`` when ``ACTIVITY_MAPPER`` is unset, so this
    resolves to the same name as before for any deployment that doesn't
    set one.

    Note that fragmenting this way loses nothing by itself - each agent
    advertises its own mapper name in its status record (see
    ``__main__.py``'s ``report_status`` calls), so a reader that gathers
    the union of those names still sees the whole fleet. It matters
    because `snapshot` below takes a single `Mapper`: anything written
    against that signature sees only the agents sharing one name.

    Parameters
    ----------
    name : str
        The mapper's scarlet name, already resolved.

    Returns
    -------
    Mapper
    """
    return Mapper(
        name,
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
