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
from dataclasses import dataclass, field


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

    @property
    def agent_id(self) -> str:
        return f"{self.app_id}_{self.node_address}"

    @staticmethod
    def from_env() -> "HarnessConfig":
        role = os.environ.get("ROLE", "worker").strip().lower()
        if role not in ("head", "worker"):
            raise ValueError(f"ROLE must be 'head' or 'worker', got {role!r}")

        app_id = os.environ.get("APP_ID")
        if not app_id:
            raise ValueError("APP_ID is required (see DESIGN_v3.md section 15.2)")

        # NODE_ADDRESS: required here, unlike scarlets' own fallback chain
        # (env var -> getNodeInfo call -> local hostname IP) - this harness
        # doesn't yet implement the getNodeInfo HTTP fallback, so callers must
        # set NODE_ADDRESS explicitly (Gustavo does this at enrollment time in
        # a real deployment; tests set it directly).
        node_address = os.environ.get("NODE_ADDRESS")
        if not node_address:
            raise ValueError(
                "NODE_ADDRESS is required (this harness does not yet implement "
                "the getNodeInfo fallback scarlets.ScarletBase supports)"
            )

        device_group = os.environ.get("DEVICE_GROUP", f"{app_id}_subagent")
        head_bus = os.environ.get("HEAD_BUS", f"{app_id}_headagent")

        return HarnessConfig(
            role=role,
            app_id=app_id,
            node_address=node_address,
            device_group=device_group,
            head_bus=head_bus,
            llm_base_url=os.environ.get("LLM_BASE_URL"),
            llm_api_key=os.environ.get("LLM_API_KEY"),
            llm_model=os.environ.get("LLM_MODEL"),
            # float()/int() raise ValueError on a malformed override - fail
            # loud on bad config, same as ROLE's validation above, rather
            # than silently falling back.
            timeout_scan_interval=float(os.environ.get("TIMEOUT_SCAN_INTERVAL", "0.5")),
            max_attempts=int(os.environ.get("MAX_ATTEMPTS", "2")),
            reply_slack=float(os.environ.get("REPLY_SLACK", "10.0")),
            max_check_ins=int(os.environ.get("MAX_CHECK_INS", "2")),
            check_in_timeout=float(os.environ.get("CHECK_IN_TIMEOUT", "10.0")),
        )
