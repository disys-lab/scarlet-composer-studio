"""Raised when converse runs out of turns without a final answer."""


class ConversationDidNotConclude(RuntimeError):
    """
    Raised when the model keeps calling tools past `max_turns` without ever producing a final answer.

    Delivered via `converse`'s `on_done` error argument, not a real raise
    across threads. A real safety limit, not a soft warning: without
    one, a model stuck in a tool-calling loop runs indefinitely.

    Parameters
    ----------
    message : str
    messages : list of dict
        Full transcript so far, for post-mortem.

    Attributes
    ----------
    messages : list of dict
    """

    def __init__(self, message: str, messages: list[dict]):
        super().__init__(message)
        self.messages = messages  # full transcript so far, for post-mortem
