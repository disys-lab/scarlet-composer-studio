"""
Test doubles shared across test modules.
"""


class ScriptedLLMClient:
    """
    Fake LLM client for testing head.converse()'s loop logic without a real
    backend - implements the same chat(messages, tools) -> dict surface as
    LLMClient (see llm/client.py's canonical message shape), just returns a
    pre-scripted sequence of turns instead of calling a real model. The loop
    code never knows the difference.
    """

    def __init__(self, turns: list[dict]):
        self._turns = list(turns)
        self.calls: list[tuple[list[dict], list[dict] | None]] = []

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        # record a snapshot, not the live list, so later mutation of
        # `messages` by the caller doesn't retroactively change what a test
        # sees this call having received
        self.calls.append(([dict(m) for m in messages], tools))
        if not self._turns:
            raise AssertionError("ScriptedLLMClient ran out of scripted turns")
        return self._turns.pop(0)


def assistant_tool_call(call_id: str, name: str, arguments: dict | None = None) -> dict:
    """Convenience builder for a scripted assistant turn that calls one tool."""
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": call_id, "name": name, "arguments": arguments or {}}],
    }


def assistant_final(content: str) -> dict:
    """Convenience builder for a scripted final (no tool call) assistant turn."""
    return {"role": "assistant", "content": content, "tool_calls": []}
