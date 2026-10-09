"""The head's turn loop: ask the model, run the skills it calls, repeat."""
import uuid

from scarlet_agentic_harness.conversation_did_not_conclude import ConversationDidNotConclude
from scarlet_agentic_harness.conversation_store import ConversationStore
from scarlet_agentic_harness.converse_result import ConverseResult
from scarlet_agentic_harness.joiner import _Joiner


def _system_prompt(skills: dict) -> str:
    """
    The head's standing instructions.

    There was no system message here at all until this was added: the
    conversation was seeded with the user's question and a tool list, and
    nothing else.

    What this is and is not worth, measured against a live fleet rather
    than assumed. Skill *preference* was already working without it - on
    both qwen3-coder-next and claude-sonnet-4-6, a z-test question called
    `z_test` and a goodness-of-fit question called `chi2_test` with no
    system prompt present. The tool descriptions were doing that job.

    What it measurably changes is thrashing. On qwen3-coder-next, same
    two questions, counting the head's own tool calls:

        no system prompt    z_test + 7 more calls;  chi2_test twice + 5 more
        with this prompt    z_test + 3;             chi2_test once + 3

    The redundant second `chi2_test` and the stray `combine` calls go
    away. The "never estimate a p-value" paragraph is there for a real
    observed answer: asked for a chi-squared test, the head once reported
    "the standardized z-score is approximately -4.444, so P(Z > -4.444)
    is approximately 1" - a p-value produced from memory rather than from
    `distribution`.

    The list of dedicated skills is built from the registry rather than
    written out, so a contributed skill is named here the moment it is
    registered and this cannot go stale.

    Parameters
    ----------
    skills : dict
        The registry, name -> Skill.

    Returns
    -------
    str
    """
    composed = sorted(n for n, s in skills.items() if hasattr(s, "plan"))
    names = ", ".join(composed)
    return (
        "You coordinate a fleet of agents, each holding its own slice of a "
        "dataset. You answer by calling skills; you never see raw rows.\n\n"
        f"PREFER A DEDICATED SKILL. These compute a complete statistic in "
        f"one call: {names}. If one of them answers the question, call it "
        "and do not rebuild it from parts. They already handle column "
        "agreement, the aggregation, the arithmetic and the p-value, and "
        "they have been tested against scipy.\n\n"
        "`sum_core`, `combine` and `distribution` are low-level building "
        "blocks. Reach for them only when no dedicated skill fits - for "
        "example a chi-squared test *for a variance*, which `chi2_test` "
        "does not do (it is goodness-of-fit). When you do compose by hand, "
        "say so in your answer and say why no dedicated skill applied.\n\n"
        "Do not do arithmetic yourself, and never estimate a p-value from "
        "memory or by a normal approximation. Call `distribution`. A "
        "statistic you computed in your own reasoning is not a result the "
        "fleet produced.\n\n"
        "RESULTS ARE PER-COLUMN AND POSITIONAL. A skill returns `result` "
        "as a list lined up with its `columns` list, index for index. If "
        "the question names one column, pass `columns` with just that one; "
        "otherwise you get every shared column back and have to pick the "
        "right index yourself. Never read element 0 as the answer without "
        "checking `columns`. Observed: a variance test asked about "
        "vibration_rms returned columns [power_kw, shaft_speed_rpm, "
        "vibration_rms], and the answer reported power_kw's statistic "
        "labelled as vibration_rms.\n\n"
        "State the number you got, the skill that produced it, and what it "
        "means for the question asked."
    )


class ToolCallCallbacks:
    """
    The two callbacks belonging to one tool call in one turn.

    They exist per call, not per turn: a turn routinely issues several
    calls at once, and each needs to report its own result and its own
    dispatches. Correlating by timestamp instead would mis-attribute the
    moment two calls overlap, which is the normal case.

    Parameters
    ----------
    conversation : Conversation
        Owner, for emitting events and submitting to the joiner.
    joiner : _Joiner
        Collects results until every call in the turn has answered.
    call : dict
        The tool call, carrying ``id``, ``name`` and ``arguments``.
    turn_index : int
    """

    def __init__(self, conversation, joiner, call: dict, turn_index: int):
        self._conversation = conversation
        self._joiner = joiner
        self._call = call
        self._turn_index = turn_index

    def on_result(self, result: dict) -> None:
        """Emit the result and hand it to the joiner."""
        self._conversation.emit({
            "type": "tool_result", "turn": self._turn_index,
            "call_id": self._call["id"], "skill": self._call["name"],
            "result": result,
        })
        self._joiner.submit(self._call["id"], result)

    def on_dispatch(self, request_id: str, attempt: int) -> None:
        """
        Record which request_id(s) this call produced.

        The only place that mapping is knowable: `run_skill` mints a fresh
        request_id per *attempt*, so one call can span several, and nothing
        downstream can reconstruct which dispatch belonged to which call
        without being told.
        """
        self._conversation.emit({
            "type": "dispatch", "turn": self._turn_index,
            "call_id": self._call["id"], "skill": self._call["name"],
            "request_id": request_id, "attempt": attempt,
        })


class TurnResults:
    """
    Appends a completed turn's tool results, then starts the next turn.

    Separate from `Conversation` because `_Joiner` needs a callable that
    already knows which turn and which calls it is completing.
    """

    def __init__(self, conversation, calls: list, turn_index: int):
        self._conversation = conversation
        self._calls = calls
        self._turn_index = turn_index

    def __call__(self, results_by_id: dict) -> None:
        """Record every result in order, then advance."""
        for call in self._calls:
            self._conversation.append_message({
                "role": "tool", "tool_call_id": call["id"],
                "content": results_by_id[call["id"]],
            })
        self._conversation.do_turn(self._turn_index + 1)


class Conversation:
    """
    One `converse` exchange: the model's turns and the skills they invoke.

    Holds the state the turn loop needs - the conversation id, the store,
    the tool schemas - so the loop can be methods rather than closures over
    a single long function.

    Parameters
    ----------
    human_message : str
    config : HarnessConfig
    buses : Buses
    skills : dict
        Skill name -> instance; also the registry a compound skill needs to
        resolve its plan.
    llm_client : ChatClient
    on_done : callable
        ``(result, error) -> None``, called exactly once.
    max_turns : int
    on_event : callable or None
    store : ConversationStore or None
    dialogue : AgentDialogue or None
    """

    def __init__(self, human_message, config, buses, skills, llm_client,
                 on_done, max_turns, on_event, store, dialogue):
        self._human_message = human_message
        self._config = config
        self._buses = buses
        self._skills = skills
        self._llm_client = llm_client
        self._on_done = on_done
        self._max_turns = max_turns
        self._on_event = on_event
        self._dialogue = dialogue
        self._store = store if store is not None else ConversationStore()
        self.conv_id = str(uuid.uuid4())
        self._tools = [s.as_tool_schema() for s in skills.values()]

    def run(self) -> None:
        """Seed the store with the question and take the first turn."""
        self._store.create(self.conv_id, {
            "messages": [{"role": "system", "content": _system_prompt(self._skills)},
                         {"role": "user", "content": self._human_message}]})
        # The question that started all this. Without it a consumer sees a
        # conversation's reasoning and its answer but never what was asked.
        self.emit({"type": "question", "content": self._human_message})
        self.do_turn(0)

    def emit(self, event: dict) -> None:
        """
        Publish one event, stamped with this conversation's id.

        conv_id is stamped here rather than left to the caller because it is
        minted in this object - a caller cannot know it beforehand, and
        without it concurrent conversations are indistinguishable in a
        shared event stream.
        """
        if self._on_event is not None:
            self._on_event({"conv_id": self.conv_id, **event})

    def append_message(self, message: dict) -> None:
        """Add one message to this conversation's transcript."""
        self._store.append(self.conv_id, "messages", message)

    def _finish(self, result, error) -> None:
        """Drop the transcript and report the outcome exactly once."""
        self._store.forget(self.conv_id)
        self._on_done(result, error)

    def do_turn(self, turn_index: int) -> None:
        """
        Run one turn: ask the model, then dispatch whatever it calls.

        Parameters
        ----------
        turn_index : int
            Zero-based. Reaching `max_turns` ends the conversation with
            `ConversationDidNotConclude`.
        """
        # Everything here is wrapped because turn 0 and every later turn run
        # on different threads. Turn 0 is called by run(), on the caller's
        # thread, so an exception reaches the caller. Turns 1+ are called by
        # TurnResults when the joiner fires - on a bus callback thread, where
        # an exception dies silently, _finish never runs, on_done never
        # fires, and the caller waits forever.
        #
        # Observed: the endpoint returned HTTP 400 on a mid-conversation
        # turn, the client correctly did not retry, and the notebook then sat
        # idle for eleven minutes until its cell limit killed it. The failure
        # was instant; only the reporting of it hung.
        try:
            if turn_index >= self._max_turns:
                messages = self._store.get(self.conv_id)["messages"]
                self._finish(None, ConversationDidNotConclude(
                    f"model did not produce a final answer within "
                    f"{self._max_turns} turns", messages))
                return

            messages = self._store.get(self.conv_id)["messages"]
            turn = self._llm_client.chat(messages, tools=self._tools)
            self.append_message(turn)

            if not turn["tool_calls"]:
                answer = turn["content"] or ""
                self.emit({"type": "final", "content": answer})
                self._finish(ConverseResult(
                    answer=answer,
                    messages=self._store.get(self.conv_id)["messages"]), None)
                return

            if turn.get("content"):
                # Only narration *alongside* a tool call is its own event - a
                # turn with no tool_calls already emitted "final" above with the
                # same content.
                self.emit({"type": "narration", "turn": turn_index,
                           "content": turn["content"]})

            self._dispatch_calls(turn["tool_calls"], turn_index)
        except Exception as exc:
            self.emit({"type": "error", "turn": turn_index, "detail": str(exc)})
            self._finish(None, exc)

    def _dispatch_calls(self, calls: list, turn_index: int) -> None:
        """Start every tool call in this turn; the joiner advances when all land."""
        # Reached through the head module rather than imported directly: head
        # imports this one, so a module-level import would be circular - and
        # going through head keeps run_skill patchable where callers already
        # patch it.
        from scarlet_agentic_harness import head as head_mod
        joiner = _Joiner(calls, TurnResults(self, calls, turn_index))

        for call in calls:
            skill = self._skills.get(call["name"])
            self.emit({"type": "tool_call", "turn": turn_index,
                       "call_id": call["id"], "skill": call["name"],
                       "params": call["arguments"]})
            if skill is None:
                result = {"status": "error",
                          "detail": f"unknown skill {call['name']!r}"}
                self.emit({"type": "tool_result", "turn": turn_index,
                           "call_id": call["id"], "skill": call["name"],
                           "result": result})
                joiner.submit(call["id"], result)
                continue

            callbacks = ToolCallCallbacks(self, joiner, call, turn_index)
            head_mod.run_skill(
                skill, call["arguments"], self._config, self._buses,
                callbacks.on_result, dialogue=self._dialogue,
                llm_client=self._llm_client,
                on_dispatch=callbacks.on_dispatch,
                # A compound skill needs the registry to resolve its plan's
                # steps, and on_event so each step shows as its own turn.
                # Without these, run_skill's compound branch errors and the
                # model quietly composes the result by hand - inconsistently,
                # and sometimes wrong.
                skills=self._skills, on_event=self._on_event,
            )
