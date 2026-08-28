"""
Thin OpenAI-compatible LLM client.

Deliberately not vLLM-specific or litellm-specific - both (and everything
else in this ecosystem) speak the same /v1/chat/completions shape, so a
plain `openai` SDK client pointed at a configurable base_url works for
either. Per DESIGN_v3.md section 13.1, the intended model is a Hermes-style
model served by vLLM for strong tool-calling support; nothing here assumes
that specifically, it's just what LLM_BASE_URL/LLM_MODEL will point at once
real credentials are supplied.

No credentials exist yet (per the user: litellm credentials come later), so
this client raises clearly if constructed without LLM_BASE_URL rather than
silently doing nothing - callers that don't have a backend yet should not
construct this at all (HeadAgent's tool-loop is the only caller, and it's
out of scope until real credentials exist - see head.py's module docstring).
"""
from openai import OpenAI

from scarlet_agentic_harness.config import HarnessConfig


class LLMClient:
    def __init__(self, config: HarnessConfig):
        if not config.llm_base_url:
            raise ValueError(
                "LLM_BASE_URL is not set - this harness has no LLM backend "
                "configured yet. See README for the current status."
            )
        self.model = config.llm_model or "default"
        self._client = OpenAI(
            base_url=config.llm_base_url,
            api_key=config.llm_api_key or "not-needed",
        )

    def chat(self, messages: list[dict], tools: list[dict] | None = None):
        """Thin passthrough to chat.completions.create - returns the raw response."""
        kwargs = {"model": self.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        return self._client.chat.completions.create(**kwargs)
