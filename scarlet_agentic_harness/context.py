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
    """Stand-in for a real CancellationToken when a context isn't scoped to
    one in-flight, cancellable request (e.g. run_skill()'s own top-level
    ctx, used only for coordinator_for() calls - see head.py). .cancelled
    reports "not cancelled" (a fresh, unset Event) and .on_cancel() is a
    silent no-op, so code written against ctx.cancelled/ctx.on_cancel()
    doesn't need to branch on whether a token exists."""

    def __init__(self):
        self.event = threading.Event()

    def on_cancel(self, fn) -> None:
        pass

    def update_progress(self, **kwargs) -> None:
        pass


class HarnessContext:
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
        return self.config.agent_id

    @property
    def cancelled(self) -> threading.Event:
        """Set once this request has been cancelled (see cancellation.py) -
        for code that already loops/polls a deadline, add
        `and not ctx.cancelled.is_set()` alongside it."""
        return self._cancellation.event

    def on_cancel(self, fn) -> None:
        """Register fn to run immediately, on a new thread, the moment this
        request is cancelled - for a skill doing one blocking call with no
        natural checkpoint to poll a flag at. See cancellation.py."""
        self._cancellation.on_cancel(fn)

    def report_progress(self, **kwargs) -> None:
        """
        Opt-in: let a skill's coordinate() report real, specific progress
        (e.g. `ctx.report_progress(ready_count=2, expected_count=3)`) as it
        goes - this is what makes a check-in reply grounded in genuinely
        useful detail rather than just "this request exists" (see
        cancellation.py's CancellationToken.update_progress()). A no-op
        when this context isn't scoped to a cancellable, tracked request.
        """
        self._cancellation.update_progress(**kwargs)

    def mapper(self, name: str, description: str = "") -> Mapper:
        """
        Construct a Mapper scoped to `name`. Callers (skills) must pass a
        name unique to the in-flight request (e.g. f"{skill.name}_{request_id}")
        - a shared/static name would let two concurrent invocations of the
        same skill collide on each other's keys.
        """
        return Mapper(name, description=description)

    def federator(self, name: str, op) -> Federator:
        """
        Construct a Federator scoped to `name`, same per-request naming rule
        as mapper(). Note: Federator's real __init__ signature (scarlets
        source, not the README) takes no `description` kwarg - only
        scarletName and op.
        """
        return Federator(name, op)

    def mint_scarlet(self, motivation: str) -> str:
        """
        Real LLM reasoning over a scarlet's name/type/description, for the
        case a skill's own contribute()/coordinate() decides mid-run that it
        needs shared state nobody declared in advance via
        Skill.scarlet_names() (see head.py) - see scarlet_minting.py's
        module docstring for the full rationale and why this is narrower
        than head.converse()'s tool-calling loop.

        `motivation` is this call's entire situational context - why the
        calling skill decided (in its own code) that a scarlet is needed
        right now. Returns the registered name; pass it straight into
        ctx.mapper()/ctx.federator() for the actual read/write - never
        reconstruct or guess that name separately, since nothing else
        forces the two to match (see scarlet_minting.py for why that's
        still safe here specifically).

        Raises ScarletMintingFailed if the model doesn't produce a usable
        tool call. Raises RuntimeError immediately, before any LLM call, if
        this context has no llm_client - the calling skill's own code
        decided to mint one, so a silent no-op here would hide that
        decision rather than surface it.
        """
        if self.llm_client is None:
            raise RuntimeError(
                f"{self.agent_id} has no LLM backend configured - cannot mint a scarlet via reasoning"
            )
        return mint_scarlet_with_reasoning(self.llm_client, self.agent_id, motivation)

    def _authenticate_to_composer(self) -> str:
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
        Query the data source registered as `name` in composer-api, via its
        broker - see scarlet_composer_studio_open_source/broker/main.py and
        composer-api/routers/data_sources.py for the full architecture.
        `query` is passed straight through as the broker's own /query
        request body (shape is connector-specific - e.g. {"query": "SELECT
        ..."} for the mssql connector); the result is whatever the broker's
        connector returns, unwrapped from its {error, response} envelope.

        This agent authenticates to composer-api using its own real Nebula
        identity (config.nebula_username/nebula_secret) - the same
        Gustavo-delegated login composer-ui itself uses, reusing that
        rather than a second credential type for agents - then presents
        the resulting composer session token directly to the broker as
        Bearer auth. Composer-api itself never sees the query or its
        result: this call only ever touches composer-api to authenticate
        once and to look up which broker fronts `name` - see broker/
        main.py's docstring for why the actual query/result never transits
        composer-api.

        Raises RuntimeError immediately, before any network call, if this
        config has no composer_api_url/nebula_username/nebula_secret set -
        same "raise clearly rather than silently no-op" convention as
        mint_scarlet()'s llm_client check. Raises RuntimeError if `name`
        isn't registered or this agent's Nebula identity isn't authorized
        for it (composer-api's own GET /api/data-sources already filters
        out anything this caller isn't authorized to see - see
        _is_authorized() there - so those two cases are indistinguishable
        here, same as the broker's own /authorize endpoint not leaking
        that distinction either). Raises RuntimeError if the broker itself
        reports a query failure (its own {"error": true} response).
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
        Dispatch `skill` across this agent's own peer set - using this
        context's own config/buses, not the head's - and block until the
        result arrives. This is what makes a Skill invocable by ANY agent
        (head, a coordinating worker, or a contributing worker), not only
        by head via its own top-level run_skill()/converse() entry points:
        head.run_skill() itself has no head-specific logic in it at all -
        it only ever touches whatever config/buses it's handed - so this is
        a thin synchronous wrapper around it (same "local blocking to drive
        a synchronous caller" pattern tests/helpers.py's run_skill_sync()
        uses), not a new dispatch mechanism. See skills/create_scarlet.py
        for the motivating case: a worker establishing shared aggregation/
        dissemination infrastructure with its peers on its own initiative,
        without routing through head at all.

        Deferred import: head.py imports HarnessContext already, so a
        module-level import here would be circular.

        Returns run_skill()'s result dict directly (same shape as
        run_skill_sync() in tests), or a synthetic {"status": "error",
        "retryable": True, "detail": "invoke_skill() timed out..."} if no
        result arrives within `timeout` seconds.
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
