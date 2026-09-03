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
silently doing nothing.

chat() normalizes both directions to/from a plain canonical dict shape
(_to_wire/_from_wire), rather than exposing the OpenAI SDK's raw Pydantic
response objects - this is what makes head.converse()'s loop testable with
a scripted fake client that has never seen the openai package at all: both
the real client and any fake implement the same tiny surface,
`chat(messages, tools) -> dict`.

Canonical message shape (used everywhere in this codebase, not just here):
  user:      {"role": "user", "content": "<text>"}
  assistant: {"role": "assistant", "content": <str|None>,
              "tool_calls": [{"id": str, "name": str, "arguments": dict}]}
  tool:      {"role": "tool", "tool_call_id": str, "content": <dict>}
"""
import json

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

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        wire_messages = [_to_wire(m) for m in messages]
        kwargs = {"model": self.model, "messages": wire_messages}
        if tools:
            kwargs["tools"] = tools
        response = self._client.chat.completions.create(**kwargs)
        return _from_wire(response.choices[0].message)


def _to_wire(m: dict) -> dict:
    role = m["role"]
    if role == "assistant" and m.get("tool_calls"):
        return {
            "role": "assistant",
            "content": m.get("content"),
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])},
                }
                for tc in m["tool_calls"]
            ],
        }
    if role == "tool":
        return {"role": "tool", "tool_call_id": m["tool_call_id"], "content": json.dumps(m["content"])}
    return {"role": role, "content": m.get("content", "")}


def _from_wire(message) -> dict:
    tool_calls = []
    if getattr(message, "tool_calls", None):
        for tc in message.tool_calls:
            tool_calls.append({
                "id": tc.id,
                "name": tc.function.name,
                "arguments": json.loads(tc.function.arguments) if tc.function.arguments else {},
            })
    return {"role": "assistant", "content": message.content, "tool_calls": tool_calls}
