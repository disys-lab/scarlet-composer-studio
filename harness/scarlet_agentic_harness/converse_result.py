"""The result of one converse call."""
from dataclasses import dataclass, field


@dataclass
class ConverseResult:
    """
    `converse`'s result, delivered via `on_done`, not a return value.

    Attributes
    ----------
    answer : str
        The final natural-language reply.
    messages : list of dict
        The full canonical-shape transcript (every turn, every tool
        call, every tool result) - kept for post-hoc audit, not just
        what `on_event` saw as it happened.
    """
    answer: str
    messages: list[dict] = field(default_factory=list)
