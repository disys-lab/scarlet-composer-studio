"""
HarnessContext — bundles an agent's config and buses, and constructs
request-scoped Mapper/Federator instances. Passed into every Skill handler
so a skill never has to touch env vars or bus wiring directly.
"""
import threading

import requests
from scarlets.core.Mapper import Mapper
from scarlets.formulations.Federator import Federator

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.cancellation import CancellationToken
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.scarlet_minting import ChatClient, mint_scarlet_with_reasoning


class _NoopCancellation:
    """
    Stand-in for a real `CancellationToken` on a context that isn't
    scoped to one in-flight, cancellable request (e.g. `run_skill`'s own
    top-level `ctx`, used only for `coordinator_for` calls).

    `cancelled` reports "not cancelled" (a fresh, unset `Event`) and
    `on_cancel` is a silent no-op, so code written against
    `ctx.cancelled`/`ctx.on_cancel` doesn't need to branch on whether a
    real token exists.

    Attributes
    ----------
    event : threading.Event
        A fresh, never-set event.
    """

    def __init__(self):
        self.event = threading.Event()

    def on_cancel(self, fn) -> None:
        """No-op. Parameters: `fn` (callable), ignored."""
        pass

    def update_progress(self, **kwargs) -> None:
        """No-op. Parameters: arbitrary keyword progress fields, ignored."""
        pass


class HarnessContext:
    """
    Bundles an agent's config and buses; constructs request-scoped `Mapper`/`Federator` instances.

    Passed into every `Skill` handler so a skill never has to touch env
    vars or bus wiring directly.

    Parameters
    ----------
    config : HarnessConfig
    buses : Buses
    cancellation : CancellationToken or None, optional
        Defaults to a `_NoopCancellation` when this context isn't scoped
        to one in-flight, cancellable request.
    llm_client : ChatClient or None, optional
        `None` unless the owning process has an LLM backend configured.
        `mint_scarlet` raises clearly rather than silently no-op'ing
        when it's absent.

    Attributes
    ----------
    config : HarnessConfig
    buses : Buses
    llm_client : ChatClient or None
    """

    def __init__(
        self,
        config: HarnessConfig,
        buses: Buses,
        cancellation: "CancellationToken | None" = None,
        llm_client: "ChatClient | None" = None,
    ):
        self.config = config
        self.buses = buses
        self._cancellation = cancellation if cancellation is not None else _NoopCancellation()
        # None unless the process this context belongs to has an LLM
        # backend configured (see worker.py/__main__.py) - mint_scarlet()
        # raises clearly rather than silently no-op'ing when it's absent,
        # same convention as everything else in this codebase that needs a
        # real backend to do its job.
        self.llm_client = llm_client
        # Lazily populated by query_data_source() on its first call, then
        # reused for the rest of this process's lifetime - same
        # "authenticate once, cache, reuse" discipline as llm_client itself
        # (constructed once in worker.py/__main__.py), except this one is
        # built lazily here rather than passed in, since not every worker
        # needs it and authenticating eagerly would mean every worker
        # startup depends on composer-api being reachable even when it's
        # never actually going to call query_data_source().
        self._composer_token: str | None = None

    @property
    def agent_id(self) -> str:
        """str: This agent's id, `config.agent_id`."""
        return self.config.agent_id

    @property
    def cancelled(self) -> threading.Event:
        """
        threading.Event: Set once this request has been cancelled.

        For code that already loops/polls a deadline, add
        ``and not ctx.cancelled.is_set()`` alongside it.
        """
        return self._cancellation.event

    def on_cancel(self, fn) -> None:
        """
        Register `fn` to run immediately, on a new thread, the moment this request is cancelled.

        For a skill doing one blocking call with no natural checkpoint to
        poll a flag at.

        Parameters
        ----------
        fn : callable
            Called with no arguments on cancellation.
        """
        self._cancellation.on_cancel(fn)

    def report_progress(self, **kwargs) -> None:
        """
        Report real, specific progress on this request as it happens.

        Opt-in: e.g. ``ctx.report_progress(ready_count=2, expected_count=3)``.
        This is what makes a check-in reply grounded in genuinely useful
        detail rather than just "this request exists". A no-op when this
        context isn't scoped to a cancellable, tracked request.

        Parameters
        ----------
        **kwargs
            Arbitrary progress fields, forwarded to
            `CancellationToken.update_progress`.
        """
        self._cancellation.update_progress(**kwargs)

    def mapper(self, name: str, description: str = "") -> Mapper:
        """
        Construct a `Mapper` scoped to `name`.

        Callers (skills) must pass a name unique to the in-flight request
        (e.g. ``f"{skill.name}_{request_id}"``) - a shared/static name
        would let two concurrent invocations of the same skill collide on
        each other's keys.

        Parameters
        ----------
        name : str
        description : str, optional

        Returns
        -------
        Mapper
        """
        return Mapper(name, description=description)

    def federator(self, name: str, op) -> Federator:
        """
        Construct a `Federator` scoped to `name`, same per-request naming rule as `mapper`.

        Parameters
        ----------
        name : str
        op : callable
            One of `Mapper.SUM`, `Mapper.MAX`, `Mapper.MIN`, `Mapper.MUL`.

        Returns
        -------
        Federator
        """
        return Federator(name, op)

    def mint_scarlet(self, motivation: str) -> str:
        """
        Mint a new scarlet mid-task via real LLM reasoning over its name/type/description.

        For the case a skill's own `contribute`/`coordinate` decides
        mid-run that it needs shared state nobody declared in advance via
        `Skill.scarlet_names` - see `scarlet_minting` for the full
        rationale and why this is narrower than `head.converse`'s
        tool-calling loop.

        Parameters
        ----------
        motivation : str
            This call's entire situational context - why the calling
            skill decided (in its own code) that a scarlet is needed
            right now.

        Returns
        -------
        str
            The registered scarlet name. Pass it straight into
            `mapper`/`federator` for the actual read/write - never
            reconstruct or guess that name separately, since nothing else
            forces the two to match.

        Raises
        ------
        RuntimeError
            If this context has no `llm_client` - raised immediately,
            before any LLM call, since the calling skill's own code
            decided to mint one and a silent no-op here would hide that
            decision.
        ScarletMintingFailed
            If the model doesn't produce a usable tool call.
        """
        if self.llm_client is None:
            raise RuntimeError(
                f"{self.agent_id} has no LLM backend configured - cannot mint a scarlet via reasoning"
            )
        return mint_scarlet_with_reasoning(self.llm_client, self.agent_id, motivation)

    def _authenticate_to_composer(self) -> str:
        """
        Log into composer-api with this agent's Nebula identity.

        Returns
        -------
        str
            The composer session token.

        Raises
        ------
        RuntimeError
            If the login request fails (non-200) or composer-api reports
            an error.
        """
        resp = requests.post(
            f"{self.config.composer_api_url.rstrip('/')}/api/auth/login",
            json={"credential": f"{self.config.nebula_username}:{self.config.nebula_secret}"},
            timeout=10,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"{self.agent_id}: composer-api login returned HTTP {resp.status_code}"
            )
        data = resp.json()
        if data.get("error"):
            raise RuntimeError(f"{self.agent_id}: composer-api login failed: {data.get('response')}")
        return data["response"]["token"]

    def query_data_source(self, name: str, query: dict) -> dict:
        """
        Query the centrally-registered data source `name`, via its broker.

        See `broker.main` and `composer-api`'s ``routers/data_sources.py``
        for the full architecture. This agent authenticates to
        composer-api using its own real Nebula identity
        (`HarnessConfig.nebula_username`/`nebula_secret` - the same
        Gustavo-delegated login composer-ui itself uses), then presents
        the resulting composer session token directly to the broker as
        Bearer auth. Composer-api itself never sees the query or its
        result - this call only ever touches composer-api to
        authenticate once and to look up which broker fronts `name`.

        Parameters
        ----------
        name : str
            Name of a data source registered in composer-api.
        query : dict
            Passed straight through as the broker's own ``/query``
            request body - shape is connector-specific (e.g.
            ``{"query": "SELECT ..."}`` for the mssql connector).

        Returns
        -------
        dict
            Whatever the broker's connector returns, unwrapped from its
            ``{error, response}`` envelope.

        Raises
        ------
        RuntimeError
            If this config has no `composer_api_url`/`nebula_username`/
            `nebula_secret` set (raised immediately, before any network
            call); if `name` isn't registered or this agent's Nebula
            identity isn't authorized for it (composer-api's own
            authorization filter makes those two cases
            indistinguishable here, deliberately); or if the broker
            itself reports a query failure.
        """
        if not (self.config.composer_api_url and self.config.nebula_username and self.config.nebula_secret):
            raise RuntimeError(
                f"{self.agent_id} has no composer_api_url/nebula_username/nebula_secret configured "
                "(set COMPOSER_API_URL/NEBULA_USERNAME/NEBULA_SECRET) - cannot query a data source"
            )

        if self._composer_token is None:
            self._composer_token = self._authenticate_to_composer()

        composer_api_url = self.config.composer_api_url.rstrip("/")

        def _list_data_sources() -> requests.Response:
            return requests.get(
                f"{composer_api_url}/api/data-sources",
                headers={"Authorization": f"Bearer {self._composer_token}"},
                timeout=10,
            )

        resp = _list_data_sources()
        if resp.status_code == 401:
            # Cached token expired mid-process (composer's session TTL,
            # default 12h) - re-authenticate once and retry, rather than
            # failing a long-running worker for a stale cache alone.
            self._composer_token = self._authenticate_to_composer()
            resp = _list_data_sources()
        if resp.status_code != 200:
            raise RuntimeError(f"{self.agent_id}: GET /api/data-sources returned HTTP {resp.status_code}")

        data = resp.json()
        if data.get("error"):
            raise RuntimeError(f"{self.agent_id}: GET /api/data-sources failed: {data.get('response')}")

        entries = data["response"]["data_sources"]
        entry = next((e for e in entries if e["name"] == name), None)
        if entry is None:
            raise RuntimeError(
                f"{self.agent_id}: data source {name!r} is not registered, or this agent's Nebula "
                "identity isn't authorized for it"
            )

        broker_resp = requests.post(
            f"{entry['broker_url'].rstrip('/')}/query",
            json=query,
            headers={"Authorization": f"Bearer {self._composer_token}"},
            timeout=30,
        )
        if broker_resp.status_code != 200:
            raise RuntimeError(
                f"{self.agent_id}: broker for {name!r} returned HTTP {broker_resp.status_code}: {broker_resp.text}"
            )
        broker_data = broker_resp.json()
        if broker_data.get("error"):
            raise RuntimeError(f"{self.agent_id}: query against {name!r} failed: {broker_data.get('response')}")
        return broker_data["response"]

    def invoke_skill(self, skill: "Skill", params: dict, timeout: float = 60.0, **run_skill_kwargs) -> dict:
        """
        Dispatch `skill` across this agent's own peer set and block until the result arrives.

        Uses this context's own config/buses, not the head's. This is
        what makes a `Skill` invocable by *any* agent (head, a
        coordinating worker, or a contributing worker), not only by head
        via its own top-level `run_skill`/`converse` entry points:
        `head.run_skill` has no head-specific logic in it at all - it
        only ever touches whatever config/buses it's handed - so this is
        a thin synchronous wrapper around it, not a new dispatch
        mechanism. See `skills.create_scarlet` for the motivating case: a
        worker establishing shared aggregation/dissemination
        infrastructure with its peers on its own initiative, without
        routing through head at all.

        Parameters
        ----------
        skill : Skill
        params : dict
            Skill invocation parameters.
        timeout : float, optional
            Seconds to wait for a result before giving up. Default `60.0`.
        **run_skill_kwargs
            Forwarded to `head.run_skill`.

        Returns
        -------
        dict
            `head.run_skill`'s result dict directly, or a synthetic
            ``{"status": "error", "retryable": True, "detail": "invoke_skill() timed out..."}``
            if no result arrives within `timeout` seconds.
        """
        from scarlet_agentic_harness import head as head_mod

        done = threading.Event()
        box: dict = {}

        def on_result(result: dict) -> None:
            box["result"] = result
            done.set()

        head_mod.run_skill(skill, params, self.config, self.buses, on_result, **run_skill_kwargs)
        if not done.wait(timeout=timeout):
            return {
                "status": "error",
                "detail": f"invoke_skill({skill.name!r}) timed out after {timeout}s waiting for a result",
                "retryable": True,
            }
        return box["result"]
