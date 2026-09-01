"""
Head-side orchestration - async.

run_skill() dispatches one skill invocation and returns immediately; the
result arrives later via `on_result`, never as a return value. This
replaces a blocking wait (send, then sit on buses.global_router.receive_for()
until a reply or timeout) with buses.global_router.on_key()'s non-blocking
registration - see router.py for why: no thread should sit idle for up to
~15+ seconds waiting on one reply when it could be servicing something
else, and this is what actually lets a future check-in conversation happen
*during* that wait instead of only before or after it.

Retry is no longer a for-loop - it can't be, since nothing blocks between
attempts. It's a chain of callbacks: on_timeout or an "ok": False,
"retryable": True result triggers another call to the same inner attempt()
closure, with a fresh request_id and worker survey, up to max_attempts.
The `retryable` flag convention is unchanged from the synchronous version -
see the docstring on run_skill() below. A retry also broadcasts skill_cancel
to the superseded attempt's workers before starting the next one - without
it, whichever worker was still coordinating that attempt keeps running
until its own coordinate_timeout expires on its own, uselessly, even
though the head has already moved on and nothing is waiting on its answer
anymore (see cancellation.py, worker.py's registry).

Deliberation (optional - see `dialogue`/`llm_client` below): a plain
timeout used to mean an immediate, mechanical retry. When both are given,
on_timeout instead starts a real conversation with the coordinator
(AgentDialogue - dialogue.py), grounded in the coordinator's own real
state (see observability.py's activity registry, which is what a
worker's context_fn now draws on). Neither side of this conversation is
fixed text: _compose_checkin_question() has an LLM write the opening
question itself (varying with the skill, the timeout, and which check-in
round this is), the coordinator's reply is likewise real generation (see
dialogue.py), and _deliberate_or_followup() then weighs the whole
exchange so far and decides WAIT (re-arm the same wait, no retry yet),
RETRY (proceed with the existing cancel-and-retry path), or - if the
reply left something worth probing - a genuine follow-up question,
continuing the same conversation via dialogue.reply() before deciding.
Bounded on three axes so this can never hang or loop forever:
max_check_ins caps how many separate check-ins this can happen per
attempt, check_in_max_turns caps how many question/answer rounds one
check-in's own conversation may run before a decision is forced, and
check_in_timeout bounds the whole check-in exchange (all its rounds)
independently of the coordinator's own coordinate_timeout. Falls back to
exactly the old mechanical behavior (immediate retryable failure)
whenever dialogue/llm_client aren't supplied - existing callers are
unaffected.

converse() is the same shift applied to the LLM tool-calling loop: each
turn dispatches its tool calls concurrently (they're independent async
calls now, not sequential blocking ones) and resumes the next turn via
on_done once every call in the turn has replied. The running transcript
(previously a local `messages` list, safe because one thread's stack owned
the whole loop) now lives in a ConversationStore (conversation_store.py),
since no single thread's stack spans a conversation that's relayed across
callback threads - see that module's docstring for why.

Neither of these functions block their caller. tests/helpers.py's
run_skill_sync()/converse_sync() give tests (and __main__.py's interactive
CLI mode) a way to wait for one specific call's result via a
threading.Event, which is legitimate local blocking to drive a synchronous
caller - not blocking inside this module's own logic, which is exactly the
thing this rewrite removes.
"""
import threading
import uuid
from dataclasses import dataclass, field
from typing import Callable, Protocol

from scarlets.utils.RedisLogger import RedisLogger
from scarlets.utils.ScarletUtils import register_scarlet_definition

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.conversation_store import ConversationStore
from scarlet_agentic_harness.dialogue import AgentDialogue
from scarlet_agentic_harness.skills.base import Skill


class ChatClient(Protocol):
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict: ...


def _deliberate(llm_client: ChatClient, coordinator_reply: str, coordinate_timeout: float) -> bool:
    """
    True = keep waiting, False = retry now. A single, narrow LLM call -
    not converse()'s tool-calling loop, this isn't about choosing a skill,
    it's about weighing one piece of qualitative evidence. Defaults to
    False (retry) whenever the model's answer isn't clearly "wait" - the
    conservative choice, matching every other default-to-safe convention
    in this codebase (e.g. Skill results default to not-retryable unless
    explicitly marked otherwise).
    """
    prompt = (
        f"A distributed computation's coordinator has not produced a final "
        f"answer within its expected time (about {coordinate_timeout:.0f}s). "
        f"Asked for a status update, it replied:\n\n"
        f'"{coordinator_reply}"\n\n'
        f"Based only on this reply, should we give it more time, or treat "
        f"this as stuck and retry with a different worker? Reply with "
        f"exactly one word: WAIT or RETRY."
    )
    turn = llm_client.chat([{"role": "user", "content": prompt}])
    answer = (turn.get("content") or "").strip().upper()
    return answer.startswith("WAIT")


def _compose_checkin_question(
    llm_client: ChatClient, skill_name: str, request_id: str, coordinate_timeout: float,
    check_in_num: int, max_check_ins: int,
) -> str:
    """
    Composes the head's own opening check-in question - real LLM reasoning,
    not a fixed template, so the question itself can vary with the
    situation instead of asking the same fixed sentence every time. Falls
    back to a plain, functional question if the model returns nothing
    usable, so a check-in can never silently stall on an empty reply.
    """
    prompt = (
        f"A distributed {skill_name!r} computation (request {request_id}) hasn't produced "
        f"a final result within its expected time (about {coordinate_timeout:.0f}s). "
        f"You're about to check in with the agent coordinating it - this is check-in "
        f"{check_in_num + 1} of {max_check_ins} you're allowed before deciding to retry "
        f"with a different worker instead.\n\n"
        f"Write a short, natural message asking them for a status update. Reply with "
        f"just the message itself, addressed to them directly - it will be sent verbatim."
    )
    turn = llm_client.chat([{"role": "user", "content": prompt}])
    question = (turn.get("content") or "").strip()
    return question or (
        f"You're coordinating a {skill_name!r} computation (request {request_id}) that "
        f"hasn't produced a final result within its expected time. How is it going - "
        f"still waiting on contributors, or has something gone wrong?"
    )


def _deliberate_or_followup(
    llm_client: ChatClient, transcript: list[dict], skill_name: str, coordinate_timeout: float,
    allow_followup: bool,
) -> dict:
    """
    The multi-turn sibling of _deliberate(): given the whole check-in
    conversation so far (not just the latest reply), decide whether to
    keep waiting, retry now, or ask a genuine follow-up before deciding -
    real reasoning over open-ended text either way, never a keyword match
    or a fixed script. allow_followup is False once check_in_max_turns is
    reached, forcing a real decision instead of stalling in a loop.
    Defaults to retry (the conservative choice - see _deliberate()'s
    docstring) whenever the model's answer doesn't clearly parse as one of
    the allowed actions.
    """
    convo = "\n".join(
        f"{'You' if turn['speaker'] == 'head' else 'Coordinator'}: {turn['content']}"
        for turn in transcript
    )
    followup_line = (
        '- "ASK: <your question>" to ask a specific follow-up before deciding, if their '
        "reply left something worth probing or was too vague to act on\n"
        if allow_followup else ""
    )
    prompt = (
        f"You're checking in on the coordinator of a distributed {skill_name!r} "
        f"computation that hasn't produced a final result within its expected time "
        f"(about {coordinate_timeout:.0f}s). Here is the check-in conversation so far:\n\n"
        f"{convo}\n\n"
        f"Decide what to do next. Reply with exactly one of:\n"
        f'- "WAIT" to give it more time\n'
        f'- "RETRY" to treat this as stuck and retry with a different worker\n'
        f"{followup_line}"
        f"Reply with only that - nothing else."
    )
    turn = llm_client.chat([{"role": "user", "content": prompt}])
    answer = (turn.get("content") or "").strip()
    upper = answer.upper()
    if allow_followup and upper.startswith("ASK:"):
        question = answer.split(":", 1)[1].strip()
        if question:
            return {"action": "followup", "question": question}
    if upper.startswith("WAIT"):
        return {"action": "wait"}
    return {"action": "retry"}


def _default_scarlet_description(skill: Skill, params: dict, name: str) -> str:
    return f"Scarlet {name!r} backing a {skill.name!r} computation (params={params!r})."


def _compose_scarlet_description(llm_client: ChatClient, skill: Skill, params: dict, name: str) -> str:
    """
    Real LLM reasoning, not fixed text - same rationale as
    _compose_checkin_question(). The scarlet's description is fed directly
    into every agent's context window (see register_scarlet_definition()'s
    docstring), so this is grounded in the skill's own description/params
    rather than reused verbatim across every invocation, and asks for
    something concrete about the data contract rather than a restatement of
    what the skill does. Falls back to a plain, functional description if
    the model returns nothing usable - same convention as every other LLM
    call in this module.
    """
    prompt = (
        f"You're about to dispatch a distributed {skill.name!r} computation "
        f"(scarlet name {name!r}) across worker agents. The skill: "
        f"{skill.description}\n\n"
        f"Called this time with parameters: {params!r}.\n\n"
        f"Write a short, natural-language description of this specific scarlet - "
        f"what it holds and how contributing workers should use it. Be concrete "
        f"about the data shape/contract, not just a restatement of what the skill "
        f"does in general. Reply with just the description, nothing else."
    )
    turn = llm_client.chat([{"role": "user", "content": prompt}])
    description = (turn.get("content") or "").strip()
    return description or _default_scarlet_description(skill, params, name)


def _register_scarlets(skill: Skill, params: dict, mapper_name: str, llm_client: "ChatClient | None") -> None:
    """
    Mints every scarlet this attempt's skill.contribute()/coordinate() will
    construct - before dispatch, on the head, with a real description -
    rather than leaving registration to happen lazily (and blankly) the
    first time some worker constructs its own ctx.mapper()/ctx.federator().
    A no-op for skills that don't declare any (scarlet_names() defaults to
    []). See Skill.scarlet_names()'s docstring for why the *names* are
    still assigned by run_skill() deterministically (mapper_name is
    request_id-based, never LLM-authored) while only the description is
    generated - an LLM-invented name would have nothing forcing it to match
    the literal Redis key a worker's own code actually touches.
    """
    names = skill.scarlet_names(mapper_name)
    if not names:
        return
    description = (
        _compose_scarlet_description(llm_client, skill, params, mapper_name)
        if llm_client is not None
        else _default_scarlet_description(skill, params, mapper_name)
    )
    for name in names:
        register_scarlet_definition(
            scarlet_name=name,
            scarlet_type="mapper",
            description=description,
            attributes={"mode": "redis-scarlet"},
            overwrite=True,
        )


def run_skill(
    skill: Skill,
    params: dict,
    config: HarnessConfig,
    buses: Buses,
    on_result: Callable[[dict], None],
    max_attempts: int | None = None,
    reply_slack: float | None = None,
    dialogue: AgentDialogue | None = None,
    llm_client: ChatClient | None = None,
    max_check_ins: int | None = None,
    check_in_timeout: float | None = None,
    check_in_max_turns: int | None = None,
) -> None:
    """
    Dispatch one invocation of `skill` across currently-registered workers.
    Does not block and does not return the result - `on_result` fires
    exactly once, on some later thread, with the final result dict (shape:
    {"status": "ok"/"error", ...}), whether that's success, a
    non-retryable failure, or exhausting every retry attempt. Despite the
    module name, nothing here is actually head-specific - it only ever
    touches the `config`/`buses` it's handed, which is exactly what lets a
    worker call this too (see HarnessContext.invoke_skill()) to dispatch a
    skill across its own peers on its own initiative, with no head
    involvement at all. Workers are discovered fresh via GatherStatus() on
    every attempt, per DESIGN_v3.md section 8.5 - never a hardcoded
    topology, which is exactly what lets a retry naturally exclude a worker
    that went offline mid-computation without any special-cased "remove
    this worker" logic.

    A failed attempt is retried (fresh request_id, fresh worker survey,
    possibly a new coordinator) only if the result carries `"retryable":
    True` - set by a Skill's coordinate() for failures that are plausibly
    transient (a contributor never signaled ready, an AllGather/Aggregate
    call failed, the coordinator never replied at all). Failures that would
    just happen again regardless of which worker runs them (e.g. combine's
    "bad expression" errors) are not retryable, and skills that don't set
    the flag at all default to not-retryable - the conservative choice, so
    a skill written before this existed doesn't get retried by accident.
    "no worker currently reports this capability" is a precondition check
    before any dispatch happens, not a mid-computation failure, so it is
    never retried here.

    reply_slack: extra seconds beyond the coordinator's own coordinate_timeout
    that the head waits for a reply before giving up on that attempt - real
    slack accounts for message round-trip time on top of the coordinator's
    internal deadline. Overridable mainly so tests can shrink it instead of
    waiting through a real ~10s timeout to prove retry behavior.

    dialogue/llm_client: optional. If both are given, a timeout doesn't
    immediately mean retry - see the module docstring's "Deliberation"
    section. Omit either (the default) for the old, purely mechanical
    behavior. max_check_ins/check_in_timeout/check_in_max_turns only
    matter when both are given - see the same section for what they
    bound. check_in_max_turns caps how many question/answer rounds a
    single check-in conversation may run before a decision is forced -
    both the opening question and any follow-up are themselves composed
    by an LLM call (_compose_checkin_question/_deliberate_or_followup),
    not fixed text, so the exchange can genuinely vary with what the
    coordinator actually says instead of following one fixed script.

    max_attempts/reply_slack/max_check_ins/check_in_timeout/
    check_in_max_turns each default to None, meaning "use config's value"
    (HarnessConfig.max_attempts etc. - see config.py, settable via env var
    for a real deployment) - pass an explicit value here (as tests do) to
    override just this one call.
    """
    max_attempts = max_attempts if max_attempts is not None else config.max_attempts
    reply_slack = reply_slack if reply_slack is not None else config.reply_slack
    max_check_ins = max_check_ins if max_check_ins is not None else config.max_check_ins
    check_in_timeout = check_in_timeout if check_in_timeout is not None else config.check_in_timeout
    check_in_max_turns = check_in_max_turns if check_in_max_turns is not None else config.check_in_max_turns

    ctx = HarnessContext(config, buses)

    def attempt(attempt_num: int) -> None:
        workers_info = buses.gather_workers()
        workers = [w for w, rec in workers_info.items() if skill.name in rec.get("capabilities", [])]
        if not workers:
            on_result({"status": "error", "detail": f"no online worker currently reports the {skill.name!r} capability"})
            return

        request_id = str(uuid.uuid4())
        coordinator = skill.coordinator_for(ctx, workers)

        request = {
            "request_id": request_id,
            "skill": skill.name,
            "mapper_name": f"{skill.name}_{request_id}",
            "coordinator": coordinator,
            "workers": workers,
            "params": params,
        }

        # Register before dispatch, not after - see _register_scarlets()'s
        # docstring. A blocking Redis write, so it's guaranteed to land
        # before any worker can construct its own (blank-description,
        # no-op-against-an-existing-key) Mapper()/Federator() in response
        # to the Send below.
        _register_scarlets(skill, params, request["mapper_name"], llm_client)

        # Defined here (not shared across attempts) so it closes over this
        # attempt's own request_id/workers - needed to broadcast
        # skill_cancel to exactly this attempt's workers if it's the one
        # that ends up superseded by a retry.
        def handle(result: dict) -> None:
            if result.get("status") == "ok":
                RedisLogger.info(f"[{config.agent_id}] {skill.name!r} request={request_id} succeeded")
                on_result(result)
                return
            if not result.get("retryable", False) or attempt_num >= max_attempts:
                RedisLogger.info(
                    f"[{config.agent_id}] {skill.name!r} request={request_id} failed permanently: "
                    f"{result.get('detail')}"
                )
                on_result(result)
                return
            RedisLogger.info(
                f"[{config.agent_id}] {skill.name!r} request={request_id} failed (retryable): "
                f"{result.get('detail')} - retrying as attempt {attempt_num + 1}"
            )
            for worker_id in workers:
                buses.global_bus.Send(worker_id, {"type": "skill_cancel", "request_id": request_id})
            attempt(attempt_num + 1)

        RedisLogger.info(
            f"[{config.agent_id}] dispatching {skill.name!r} request={request_id} "
            f"attempt={attempt_num} coordinator={coordinator} workers={workers}"
        )
        for worker_id in workers:
            msg_type = "skill_coordinate" if worker_id == coordinator else "skill_contribute"
            buses.global_bus.Send(worker_id, {"type": msg_type, **request})

        if coordinator == config.agent_id:
            # Only reached if a skill explicitly overrides coordinator_for()
            # to return the invoking agent's own id - not the default,
            # regardless of whether that invoker is the head or a worker
            # calling this via HarnessContext.invoke_skill(). Still
            # dispatched onto a new thread rather than run inline, so
            # run_skill() never blocks its own caller even in this rare
            # case.
            def run_in_process():
                handle(skill.coordinate(ctx, request, workers))
            threading.Thread(target=run_in_process, daemon=True).start()
            return

        def on_reply(msg: dict) -> None:
            handle(msg.get("body", {}))

        def wait_for_reply() -> None:
            # No explicit forget() needed here, unlike the old receive_for()
            # flow - on_key()'s callback/timeout pair is self-cleaning
            # either way it resolves (see router.py).
            buses.global_router.on_key(
                request_id, on_reply,
                timeout=skill.coordinate_timeout + reply_slack, on_timeout=lambda: on_timeout(0),
            )

        def on_timeout(check_in_num: int) -> None:
            if dialogue is None or llm_client is None or check_in_num >= max_check_ins:
                handle({"status": "error", "detail": "coordinator did not respond in time", "retryable": True})
                return

            RedisLogger.info(
                f"[{config.agent_id}] {skill.name!r} request={request_id} coordinator {coordinator!r} "
                f"has not replied - checking in (round {check_in_num + 1}/{max_check_ins})"
            )

            # Two independent ways this check-in can resolve - the
            # coordinator's conversation concludes in a decision, or
            # check_in_timeout expires first (bounding the *whole*
            # exchange, including any follow-up rounds) - only one may
            # ever act, whichever gets here first.
            resolved = [False]
            resolve_lock = threading.Lock()

            def resolve_once(action: Callable[[], None]) -> None:
                with resolve_lock:
                    if resolved[0]:
                        return
                    resolved[0] = True
                action()

            def on_checkin_timeout() -> None:
                RedisLogger.info(
                    f"[{config.agent_id}] {skill.name!r} request={request_id} coordinator {coordinator!r} "
                    f"did not answer the check-in itself"
                )
                resolve_once(lambda: handle({
                    "status": "error",
                    "detail": "coordinator did not respond in time (unresponsive to check-in)",
                    "retryable": True,
                }))

            timer = threading.Timer(check_in_timeout, on_checkin_timeout)
            timer.daemon = True
            timer.start()

            # transcript/turns_used are shared, mutable state closed over by
            # on_checkin_reply, which re-enters itself (via dialogue.reply)
            # for as many follow-up rounds as check_in_max_turns allows -
            # both the opening question and every follow-up are composed by
            # a real LLM call grounded in the actual conversation so far,
            # not fixed text, so this exchange can genuinely go wherever the
            # coordinator's own answer leads it, within that bound.
            transcript: list[dict] = []
            turns_used = [0]

            def on_checkin_reply(content: str, sender: str) -> None:
                transcript.append({"speaker": "coordinator", "content": content})
                allow_followup = turns_used[0] < check_in_max_turns
                decision = _deliberate_or_followup(
                    llm_client, transcript, skill.name, skill.coordinate_timeout, allow_followup,
                )
                RedisLogger.info(
                    f"[{config.agent_id}] {skill.name!r} request={request_id} check-in reply from "
                    f"{sender!r}: {content!r} - decision: {decision}"
                )
                if decision["action"] == "followup":
                    turns_used[0] += 1
                    question = decision["question"]
                    transcript.append({"speaker": "head", "content": question})
                    dialogue.reply(coordinator, conv_id, question, on_checkin_reply)
                elif decision["action"] == "wait":
                    resolve_once(wait_for_reply)
                else:
                    resolve_once(lambda: handle({
                        "status": "error",
                        "detail": f"coordinator did not respond in time (checked in, decided to retry: {content!r})",
                        "retryable": True,
                    }))

            opening_question = _compose_checkin_question(
                llm_client, skill.name, request_id, skill.coordinate_timeout, check_in_num, max_check_ins,
            )
            transcript.append({"speaker": "head", "content": opening_question})
            turns_used[0] += 1
            conv_id = dialogue.start(coordinator, opening_question, on_checkin_reply)

        wait_for_reply()

    attempt(1)


class ConversationDidNotConclude(RuntimeError):
    """Raised (via on_done's error argument, not a real raise across
    threads) if the model keeps calling tools past max_turns without ever
    producing a final answer - a real safety limit, not a soft warning:
    without one, a model stuck in a tool-calling loop runs indefinitely."""

    def __init__(self, message: str, messages: list[dict]):
        super().__init__(message)
        self.messages = messages  # full transcript so far, for post-mortem


@dataclass
class ConverseResult:
    """
    converse()'s result (delivered via on_done, not a return value).
    `answer` is the final string; `messages` is the full canonical-shape
    transcript (every turn, every tool call, every tool result) - kept for
    post-hoc audit, not just what on_event saw as it happened.
    """
    answer: str
    messages: list[dict] = field(default_factory=list)


class _Joiner:
    """
    Collects N async tool-call results for one turn, then runs
    `on_all_done` exactly once with every result, keyed by call id in the
    turn's original order - not completion order, which varies now that
    each tool call dispatches independently instead of one after another.
    The decrement-and-check is done atomically under one lock so exactly
    one thread ever observes "that was the last one", regardless of which
    call's result arrives last.
    """

    def __init__(self, calls: list[dict], on_all_done: Callable[[dict], None]):
        self._calls = calls
        self._on_all_done = on_all_done
        self._results: dict[str, dict] = {}
        self._remaining = len(calls)
        self._lock = threading.Lock()

    def submit(self, call_id: str, result: dict) -> None:
        with self._lock:
            self._results[call_id] = result
            self._remaining -= 1
            done = self._remaining == 0
        if done:
            ordered = {call["id"]: self._results[call["id"]] for call in self._calls}
            self._on_all_done(ordered)


def converse(
    human_message: str,
    config: HarnessConfig,
    buses: Buses,
    skills: dict[str, Skill],
    llm_client: ChatClient,
    on_done: Callable[["ConverseResult | None", Exception | None], None],
    max_turns: int = 5,
    on_event: Callable[[dict], None] | None = None,
    store: ConversationStore | None = None,
    dialogue: AgentDialogue | None = None,
) -> None:
    """
    Turn one human message into zero or more skill invocations and a final
    natural-language reply. Does not block and does not return anything -
    `on_done(result, error)` fires exactly once, on some later thread, with
    either a ConverseResult or a ConversationDidNotConclude (never both).

    A single call can involve multiple tool-call turns, and a single turn
    can request multiple tool calls at once - those now dispatch
    concurrently (via run_skill(), itself non-blocking) rather than one
    after another, since nothing requires waiting for call 1's reply
    before starting call 2 anymore. The turn only advances once every call
    in it has replied (see _Joiner), and results are placed back into the
    transcript in the original call order regardless of which finished
    first, so the model always sees a deterministic conversation shape.

    dialogue: optional - if given, every run_skill() call this conversation
    makes gets deliberation on timeout (see run_skill()'s docstring)
    instead of an immediate mechanical retry, reusing this same
    `llm_client` for the deliberation call itself (no separate client
    needed - it's the same backend either way).

    llm_client.chat() itself is still an ordinary blocking call - only the
    bus-mediated waiting (skill results, and eventually check-in replies)
    is non-blocking. Blocking the thread currently running a turn for the
    LLM round-trip doesn't stall anything else, since it isn't a router's
    polling thread.

    If `on_event` is given, it is called synchronously (on whichever thread
    is running that turn, in order for that turn) for:
      - {"type": "narration", "turn": i, "content": ...} whenever a turn
        carries non-empty content alongside tool calls.
      - {"type": "tool_call", "turn": i, "call_id", "skill", "params"}
        right before dispatch.
      - {"type": "tool_result", "turn": i, "call_id", "skill", "result"}
        right after a reply arrives.
      - {"type": "final", "content": ...} when the loop concludes.
    """
    store = store if store is not None else ConversationStore()
    conv_id = str(uuid.uuid4())
    tools = [s.as_tool_schema() for s in skills.values()]
    store.create(conv_id, {"messages": [{"role": "user", "content": human_message}]})

    def emit(event: dict) -> None:
        if on_event is not None:
            on_event(event)

    def finish(result: ConverseResult | None, error: Exception | None) -> None:
        store.forget(conv_id)
        on_done(result, error)

    def do_turn(turn_index: int) -> None:
        if turn_index >= max_turns:
            messages = store.get(conv_id)["messages"]
            finish(None, ConversationDidNotConclude(
                f"model did not produce a final answer within {max_turns} turns", messages))
            return

        messages = store.get(conv_id)["messages"]
        turn = llm_client.chat(messages, tools=tools)
        store.append(conv_id, "messages", turn)

        if not turn["tool_calls"]:
            answer = turn["content"] or ""
            emit({"type": "final", "content": answer})
            finish(ConverseResult(answer=answer, messages=store.get(conv_id)["messages"]), None)
            return

        if turn.get("content"):
            # Only the "narration alongside a tool call" case counts as a
            # separate event - a turn with no tool_calls already emits
            # "final" above with the same content.
            emit({"type": "narration", "turn": turn_index, "content": turn["content"]})

        calls = turn["tool_calls"]

        def on_all_results(results_by_id: dict) -> None:
            for call in calls:
                store.append(conv_id, "messages", {
                    "role": "tool", "tool_call_id": call["id"], "content": results_by_id[call["id"]],
                })
            do_turn(turn_index + 1)

        joiner = _Joiner(calls, on_all_results)

        for call in calls:
            skill = skills.get(call["name"])
            emit({"type": "tool_call", "turn": turn_index, "call_id": call["id"], "skill": call["name"], "params": call["arguments"]})
            if skill is None:
                result = {"status": "error", "detail": f"unknown skill {call['name']!r}"}
                emit({"type": "tool_result", "turn": turn_index, "call_id": call["id"], "skill": call["name"], "result": result})
                joiner.submit(call["id"], result)
            else:
                def on_result(result: dict, call=call) -> None:
                    emit({"type": "tool_result", "turn": turn_index, "call_id": call["id"], "skill": call["name"], "result": result})
                    joiner.submit(call["id"], result)
                run_skill(skill, call["arguments"], config, buses, on_result, dialogue=dialogue, llm_client=llm_client)

    do_turn(0)
