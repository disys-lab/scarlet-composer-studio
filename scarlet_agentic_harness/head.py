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
(AgentDialogue - dialogue.py) - "how's this going?" - grounded in the
coordinator's own real state (see observability.py's activity registry,
which is what a worker's context_fn now draws on). A small LLM call
weighs the reply and decides WAIT (re-arm the same wait, no retry yet) or
RETRY (proceed with the existing cancel-and-retry path). Bounded on two
axes so this can never hang or loop forever: max_check_ins caps how many
times this can happen per attempt, and check_in_timeout bounds the
check-in conversation itself, independently of the coordinator's own
coordinate_timeout. Falls back to exactly the old mechanical behavior
(immediate retryable failure) whenever dialogue/llm_client aren't
supplied - existing callers are unaffected.

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
) -> None:
    """
    Dispatch one invocation of `skill` across currently-registered workers.
    Does not block and does not return the result - `on_result` fires
    exactly once, on some later thread, with the final result dict (shape:
    {"status": "ok"/"error", ...}), whether that's success, a
    non-retryable failure, or exhausting every retry attempt. Runs on the
    head. Workers are discovered fresh via GatherStatus() on every attempt,
    per DESIGN_v3.md section 8.5 - never a hardcoded topology, which is
    exactly what lets a retry naturally exclude a worker that went offline
    mid-computation without any special-cased "remove this worker" logic.

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
    behavior. max_check_ins/check_in_timeout only matter when both are
    given - see the same section for what they bound.

    max_attempts/reply_slack/max_check_ins/check_in_timeout each default to
    None, meaning "use config's value" (HarnessConfig.max_attempts etc. -
    see config.py, settable via env var for a real deployment) - pass an
    explicit value here (as tests do) to override just this one call.
    """
    max_attempts = max_attempts if max_attempts is not None else config.max_attempts
    reply_slack = reply_slack if reply_slack is not None else config.reply_slack
    max_check_ins = max_check_ins if max_check_ins is not None else config.max_check_ins
    check_in_timeout = check_in_timeout if check_in_timeout is not None else config.check_in_timeout

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
            # to return the head - not the default. Still dispatched onto a
            # new thread rather than run inline, so run_skill() never blocks
            # its own caller even in this rare case.
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
            # coordinator answers it, or check_in_timeout expires first -
            # only one may ever act, whichever gets here first.
            resolved = [False]
            resolve_lock = threading.Lock()

            def resolve_once(action: Callable[[], None]) -> None:
                with resolve_lock:
                    if resolved[0]:
                        return
                    resolved[0] = True
                action()

            def on_checkin_reply(content: str, sender: str) -> None:
                should_wait = _deliberate(llm_client, content, skill.coordinate_timeout)
                RedisLogger.info(
                    f"[{config.agent_id}] {skill.name!r} request={request_id} check-in reply from "
                    f"{sender!r}: {content!r} - deliberation: {'wait longer' if should_wait else 'retry now'}"
                )
                if should_wait:
                    resolve_once(wait_for_reply)
                else:
                    resolve_once(lambda: handle({
                        "status": "error",
                        "detail": f"coordinator did not respond in time (checked in, decided to retry: {content!r})",
                        "retryable": True,
                    }))

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

            dialogue.start(
                coordinator,
                f"You're coordinating a {skill.name!r} computation (request {request_id}) that "
                f"hasn't produced a final result within its expected time. How is it going - still "
                f"waiting on contributors, or has something gone wrong?",
                on_checkin_reply,
            )

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
