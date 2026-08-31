"""
Environment configuration for a scarlet-agentic-harness agent process.

Env var names match scarlet_composer_agentic_design/DESIGN_v3.md section 15
exactly (REDIS_HOST/PORT/AUTH_TOKEN, APP_ID, NODE_ADDRESS, DEVICE_GROUP,
HEAD_BUS, MANAGER_HOST/PORT) so this harness is a drop-in citizen of the same
Gustavo app config shape scarlet-composer-studio itself already documents -
no new env var vocabulary invented for the platform-level identity pieces.

ROLE and the LLM_* vars are new - they don't exist in scarlet-composer-studio
itself, since "head vs. worker LLM loop" and "which OpenAI-compatible backend
to call" are concerns specific to this harness, not the underlying scarlets
primitives.
"""
import os
import socket
from dataclasses import dataclass, field

from scarlets.utils.RedisLogger import RedisLogger


def _env(key: str) -> str | None:
    """
    os.environ.get() that also treats an explicitly-empty value as absent.
    Found via a real container smoke test (docker run against the actual
    built image): scarlet-agent-base's own Dockerfile declares several
    optional vars as ENV KEY="" placeholders rather than leaving them
    genuinely unset (e.g. DEVICE_GROUP="", MANAGER_HOST="") - so does this
    harness's own Dockerfile (HEAD_BUS="", LLM_MODEL="") - and a plain
    os.environ.get(key, default) can't tell that apart from a real
    override: the key is present either way, so its own default argument
    never kicks in. device_group came back "" (not f"{app_id}_subagent")
    from a real run before this fix.
    """
    value = os.environ.get(key)
    return value if value else None


def _resolve_node_address(app_id: str, manager_host: str, manager_port: str) -> str:
    """
    Mirrors scarlets.types.ScarletBase._resolveNodeAddress() - the real,
    already-shipped implementation every other scarlets primitive
    (Messenger, etc.) uses - which this harness previously didn't call at
    all (see from_env()'s old, hard "NODE_ADDRESS is required" check).
    Priority: env var (checked by the caller, not here) -> the Gustavo
    manager's /api/v2/getNodeInfo endpoint (resolves this node's Nebula
    overlay IP via app_id, the same lookup Gustavo performs at enrollment
    time) -> local hostname IP -> "127.0.0.1" if even that fails. Matches
    ScarletBase's real request shape exactly (query param is `app_id`, not
    `node` - the docs' simplified description of this endpoint doesn't
    match the actual implementation, which is what this mirrors).

    On a successful getNodeInfo resolution, sets os.environ["NODE_ADDRESS"]
    (and DEVICE_GROUP, if not already genuinely set - see _env() above for
    why this checks _env() rather than using plain dict.setdefault(), which
    an existing DEVICE_GROUP="" placeholder would defeat the same way) as a
    side effect - same as ScarletBase does - so that scarlets primitives
    constructed later in this same process (Messenger, etc., which
    independently run this same priority chain via their own
    ScarletBase.__init__) see the already-resolved value via step 1 of
    their own chain instead of each making a redundant getNodeInfo call.
    """
    if manager_host and manager_port:
        try:
            import requests
            url = f"http://{manager_host}:{manager_port}/api/v2/getNodeInfo"
            resp = requests.get(url, params={"app_id": app_id}, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                resolved = data.get("node_address")
                if resolved:
                    os.environ["NODE_ADDRESS"] = resolved
                    device_group = data.get("device_group")
                    if device_group and not _env("DEVICE_GROUP"):
                        os.environ["DEVICE_GROUP"] = device_group
                    return resolved
        except Exception as exc:
            RedisLogger.warning(f"Could not resolve node address via getNodeInfo: {exc}")

    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "127.0.0.1"


@dataclass(frozen=True)
class HarnessConfig:
    role: str  # "head" or "worker"
    app_id: str
    node_address: str
    device_group: str
    head_bus: str

    # LLM backend - OpenAI-compatible (vLLM, litellm, or anything else that
    # speaks the /v1/chat/completions shape). None means "no backend
    # configured yet" - the harness must still be constructible and testable
    # without one, since real credentials arrive later.
    llm_base_url: str | None
    llm_api_key: str | None
    llm_model: str | None

    # Timing/retry knobs, all with defaults matching what run_skill()/
    # Buses/MessageRouter already defaulted to before these existed -
    # adding them here just makes the defaults *changeable* (via env var
    # in a real deployment, or explicitly in a test) instead of only
    # reachable by editing source or poking a private attribute. Defaulted
    # (not required) so every existing HarnessConfig(...) construction
    # across the test suite keeps working unchanged.
    timeout_scan_interval: float = 0.5  # MessageRouter's TimeoutWatcher - see router.py/timeout_watcher.py
    max_attempts: int = 2  # run_skill() - how many attempts before giving up
    reply_slack: float = 10.0  # run_skill() - extra wait beyond a coordinator's own coordinate_timeout
    max_check_ins: int = 2  # run_skill() - how many deliberation check-in rounds per attempt
    check_in_timeout: float = 10.0  # run_skill() - bound on one check-in conversation itself
    check_in_max_turns: int = 3  # run_skill() - max question/answer rounds within one check-in conversation

    @property
    def agent_id(self) -> str:
        return f"{self.app_id}_{self.node_address}"

    @staticmethod
    def from_env() -> "HarnessConfig":
        role = (_env("ROLE") or "worker").strip().lower()
        if role not in ("head", "worker"):
            raise ValueError(f"ROLE must be 'head' or 'worker', got {role!r}")

        app_id = _env("APP_ID")
        if not app_id:
            raise ValueError("APP_ID is required (see DESIGN_v3.md section 15.2)")

        # NODE_ADDRESS: same priority chain scarlets' own ScarletBase uses
        # (env var -> getNodeInfo -> local hostname IP -> "127.0.0.1") - see
        # _resolve_node_address() above. Gustavo's documented app-config
        # pattern deliberately leaves NODE_ADDRESS unset and expects the
        # agent to resolve it itself via this chain (contrary to this
        # harness's old assumption that Gustavo injected it directly - it
        # doesn't), so this is required for real Gustavo deployments to
        # work at all, not just a nice-to-have.
        node_address = _env("NODE_ADDRESS")
        if not node_address:
            node_address = _resolve_node_address(
                app_id, _env("MANAGER_HOST") or "", _env("MANAGER_PORT") or "",
            )

        # Read after node_address resolution, not before - a successful
        # getNodeInfo call above may have set DEVICE_GROUP as a side effect
        # (see _resolve_node_address()'s docstring), and an explicit env
        # var should still win over that.
        device_group = _env("DEVICE_GROUP") or f"{app_id}_subagent"
        head_bus = _env("HEAD_BUS") or f"{app_id}_headagent"

        return HarnessConfig(
            role=role,
            app_id=app_id,
            node_address=node_address,
            device_group=device_group,
            head_bus=head_bus,
            llm_base_url=_env("LLM_BASE_URL"),
            llm_api_key=_env("LLM_API_KEY"),
            llm_model=_env("LLM_MODEL"),
            # float()/int() raise ValueError on a malformed override - fail
            # loud on bad config, same as ROLE's validation above, rather
            # than silently falling back.
            timeout_scan_interval=float(os.environ.get("TIMEOUT_SCAN_INTERVAL", "0.5")),
            max_attempts=int(os.environ.get("MAX_ATTEMPTS", "2")),
            reply_slack=float(os.environ.get("REPLY_SLACK", "10.0")),
            max_check_ins=int(os.environ.get("MAX_CHECK_INS", "2")),
            check_in_timeout=float(os.environ.get("CHECK_IN_TIMEOUT", "10.0")),
            check_in_max_turns=int(os.environ.get("CHECK_IN_MAX_TURNS", "3")),
        )
