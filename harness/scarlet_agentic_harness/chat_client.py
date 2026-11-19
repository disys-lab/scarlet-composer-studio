"""The LLM chat client protocol, defined once for the whole harness."""
from typing import Protocol


class ChatClient(Protocol):
    """
    Structural type for an LLM chat client.

    Anything with a matching `chat` method satisfies this - there is no
    base class to inherit. `llm.client.LLMClient` is the real
    implementation; tests pass stubs.
    """

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """
        Send a chat turn to the model.

        Parameters
        ----------
        messages : list of dict
            Canonical-shape message history.
        tools : list of dict or None, optional
            Tool definitions the model may call.

        Returns
        -------
        dict
            The model's turn, including `tool_calls` if it called a tool.
        """
        ...
