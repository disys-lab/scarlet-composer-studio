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
        )
