"""
The head's conversation loop.

`converse` turns one human message into zero or more skill invocations
and a final natural-language reply, driving the LLM's tool calls through
`dispatch.run_skill` and joining their asynchronous results.

Dispatch itself lives in dispatch.py and is generic - see that module's
docstring. Only what is genuinely head-specific remains here: the
conversation loop, its result type, and the joiner that waits on
concurrent skill calls.
"""

import uuid
from scarlet_agentic_harness.conversation import Conversation
from typing import Callable


from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.conversation_store import ConversationStore
from scarlet_agentic_harness.dialogue import AgentDialogue
from scarlet_agentic_harness.dispatch import ChatClient, run_skill
from scarlet_agentic_harness.skills.base import Skill
from scarlet_agentic_harness.conversation_did_not_conclude import ConversationDidNotConclude
from scarlet_agentic_harness.converse_result import ConverseResult
from scarlet_agentic_harness.joiner import _Joiner








def converse(
    human_message: str,
    config: HarnessConfig,
    buses: Buses,
    skills: dict[str, Skill],
    llm_client: ChatClient,
    on_done: Callable[["ConverseResult | None", Exception | None], None],
    # Callers in this package pass config.converse_max_turns explicitly.
    # This default exists for tests and ad-hoc callers; it tracks the
    # config default rather than the old hardcoded 5, so forgetting the
    # kwarg degrades to "generous" instead of to "fails on any realistic
    # multi-skill request".
    max_turns: int = 30,
    on_event: Callable[[dict], None] | None = None,
    store: ConversationStore | None = None,
    dialogue: AgentDialogue | None = None,
) -> None:
    """
    Turn one human message into zero or more skill invocations and a final natural-language reply.

    Does not block and does not return anything - ``on_done(result,
    error)`` fires exactly once, on some later thread, with either a
    `ConverseResult` or a `ConversationDidNotConclude` (never both).

    A single call can involve multiple tool-call turns, and a single
    turn can request multiple tool calls at once - those dispatch
    concurrently (via `run_skill`, itself non-blocking) rather than one
    after another. The turn only advances once every call in it has
    replied (see `_Joiner`), and results are placed back into the
    transcript in the original call order regardless of which finished
    first, so the model always sees a deterministic conversation shape.

    `llm_client.chat` itself is still an ordinary blocking call - only
    the bus-mediated waiting (skill results, and check-in replies) is
    non-blocking. Blocking the thread currently running a turn for the
    LLM round-trip doesn't stall anything else, since it isn't a
    router's polling thread.

    Parameters
    ----------
    human_message : str
    config : HarnessConfig
    buses : Buses
    skills : dict of str to Skill
        Every skill this conversation may call, keyed by name.
    llm_client : ChatClient
    on_done : callable
        ``(result: ConverseResult | None, error: Exception | None) -> None``.
    max_turns : int, optional
        Safety limit on tool-calling turns. Default `5`.
    on_event : callable or None, optional
        If given, called synchronously (on whichever thread is running
        that turn, in order for that turn) for:

        - ``{"type": "question", "content": ...}`` once, first, carrying
          the message that started the conversation.

        - ``{"type": "narration", "turn": i, "content": ...}`` whenever
          a turn carries non-empty content alongside tool calls.
        - ``{"type": "tool_call", "turn": i, "call_id", "skill", "params"}``
          right before dispatch.
        - ``{"type": "dispatch", "turn": i, "call_id", "skill",
          "request_id", "attempt"}`` each time `run_skill` mints a
          request id for this call - once per attempt, so a retried call
          emits several. This is the only link between a tool call and
          the bus traffic it caused; nothing downstream can derive it.
        - ``{"type": "tool_result", "turn": i, "call_id", "skill", "result"}``
          right after a reply arrives.
        - ``{"type": "final", "content": ...}`` when the loop concludes.
    store : ConversationStore or None, optional
        Defaults to a fresh `ConversationStore` if not given.
    dialogue : AgentDialogue or None, optional
        If given, every `run_skill` call this conversation makes gets
        deliberation on timeout instead of an immediate mechanical
        retry, reusing this same `llm_client` for the deliberation call
        itself.
    """
    Conversation(human_message, config, buses, skills, llm_client, on_done,
                 max_turns, on_event, store, dialogue).run()
