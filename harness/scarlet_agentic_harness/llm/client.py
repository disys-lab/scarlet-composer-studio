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
    """
    Thin OpenAI-compatible LLM client, implementing the `scarlet_minting.ChatClient` protocol.

    Deliberately not vLLM-specific or litellm-specific - both (and
    everything else in this ecosystem) speak the same
    ``/v1/chat/completions`` shape, so a plain `openai` SDK client
    pointed at a configurable `base_url` works for either.

    Parameters
    ----------
    config : HarnessConfig
        Must have `llm_base_url` set.

    Attributes
    ----------
    model : str
        `config.llm_model`, or ``"default"`` if unset.

    Raises
    ------
    ValueError
        If `config.llm_base_url` is unset - raised clearly rather than
        constructing a client that would silently do nothing.
    """

    def __init__(self, config: HarnessConfig):
        if not config.llm_base_url:
            raise ValueError(
                "LLM_BASE_URL is not set - this harness has no LLM backend "
                "configured yet. See README for the current status."
            )
        self.model = config.llm_model or "default"
        # Overridable, but 0 by default - see `chat` for why.
        self.temperature = getattr(config, "llm_temperature", 0.0)
        # An explicit timeout, because the default is 600s read with 2
        # retries - one hung request blocks the head for up to 30 minutes.
        #
        # That is what made the notebook suite bimodal: a run either finished
        # in ~2 minutes or sat idle until its cell limit killed it. Traced by
        # timing the head's log - the fleet work completed in 2.5 minutes and
        # nothing was dispatched for the following 14, because `chat` never
        # returned. A completion for this workload takes seconds, so 60s is
        # already generous; the point is that it fails rather than hangs.
        self._client = OpenAI(
            base_url=config.llm_base_url,
            api_key=config.llm_api_key or "not-needed",
            timeout=config.llm_timeout,
            max_retries=config.llm_max_retries,
        )

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """
        Send one chat turn to the configured model.

        Normalizes both directions to/from a plain canonical dict shape
        (`_to_wire`/`_from_wire`) rather than exposing the OpenAI SDK's
        raw Pydantic response objects - this is what makes
        `head.converse`'s loop testable with a scripted fake client that
        has never seen the `openai` package at all.

        Parameters
        ----------
        messages : list of dict
            Canonical-shape message history: ``{"role": "user", "content": "<text>"}``,
            ``{"role": "assistant", "content": <str|None>, "tool_calls": [...]}``,
            or ``{"role": "tool", "tool_call_id": str, "content": <dict>}``.
        tools : list of dict or None, optional
            Tool definitions the model may call.

        Returns
        -------
        dict
            The model's turn in canonical assistant-message shape:
            ``{"role": "assistant", "content": ..., "tool_calls": [...]}``.
        """
        wire_messages = [_to_wire(m) for m in messages]
        # temperature=0 so the same question takes the same path twice.
        #
        # Left unset, the endpoint's default sampling made the notebook suite
        # an unreliable gate: notebook 13 failed and then passed on identical
        # code and identical data, because the head explored a longer chain of
        # tool calls on one run than the other and exhausted the cell timeout.
        # A regression suite that disagrees with itself cannot tell a real
        # break from a slow conversation.
        kwargs = {"model": self.model, "messages": wire_messages,
                  "temperature": self.temperature}
        if tools:
            kwargs["tools"] = tools
        response = self._client.chat.completions.create(**kwargs)
        return _from_wire(response.choices[0].message)


def _to_wire(m: dict) -> dict:
    """
    Convert one canonical-shape message to the OpenAI wire format.

    Parameters
    ----------
    m : dict
        A canonical-shape message (see `LLMClient.chat`).

    Returns
    -------
    dict
        The OpenAI SDK's wire-format message dict.
    """
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
    """
    Convert one OpenAI SDK response message to the canonical shape.

    Parameters
    ----------
    message : openai.types.chat.ChatCompletionMessage
        The raw SDK response message object.

    Returns
    -------
    dict
        Canonical-shape assistant message (see `LLMClient.chat`).
    """
    tool_calls = []
    if getattr(message, "tool_calls", None):
        for tc in message.tool_calls:
            tool_calls.append({
                "id": tc.id,
                "name": tc.function.name,
                "arguments": json.loads(tc.function.arguments) if tc.function.arguments else {},
            })
    return {"role": "assistant", "content": message.content, "tool_calls": tool_calls}
