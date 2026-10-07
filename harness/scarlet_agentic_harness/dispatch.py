"""
Skill dispatch - generic, and deliberately not head-specific.

`run_skill` resolves which workers advertise a skill, picks a coordinator,
sends `skill_coordinate` to it and `skill_contribute` to the rest, and
collects the result. Nothing in here knows or cares whether the caller is
a head process or a worker: `HarnessContext.invoke_skill` routes through
this same function, which is what lets any agent dispatch a skill across
its own peers.

This lived in head.py until the split. It was written when only the head
dispatched, and stayed there after worker-initiated dispatch was added -
leaving a dependency graph that read worker.py -> context.py -> head.py,
as though workers depended on the head. They do not. The comment at
context.py put it plainly, back when it still said head: "head.run_skill has
no head-specific logic in it at all".

head.py now holds only `converse`, the head's LLM tool-calling loop.
"""

import threading
import uuid
from typing import Callable, Protocol

from scarlets.utils.RedisLogger import RedisLogger
from scarlets.utils.ScarletUtils import register_scarlet_definition

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.dialogue import AgentDialogue
from scarlet_agentic_harness.skills.base import CompoundSkill, Skill


class ChatClient(Protocol):
    """Structural type for an LLM chat client - anything with a matching `chat` method satisfies this."""

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """
        Parameters
        ----------
        messages : list of dict
        tools : list of dict or None, optional

        Returns
        -------
        dict
        """
        ...



def _deliberate(llm_client: ChatClient, coordinator_reply: str, coordinate_timeout: float) -> bool:
    """
    Weigh a single check-in reply and decide whether to keep waiting.

    A single, narrow LLM call - not `converse`'s tool-calling loop, this
    isn't about choosing a skill, it's about weighing one piece of
    qualitative evidence.

    Parameters
    ----------
    llm_client : ChatClient
    coordinator_reply : str
        The coordinator's answer to a status check-in.
    coordinate_timeout : float
        The skill's `coordinate_timeout`, included in the prompt for
        context.

    Returns
    -------
    bool
        `True` to keep waiting, `False` to retry now. Defaults to
        `False` (retry) whenever the model's answer isn't clearly
        "wait" - the conservative choice, matching every other
        default-to-safe convention in this codebase.
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
    Compose the head's own opening check-in question.

    Real LLM reasoning, not a fixed template, so the question itself can
    vary with the situation instead of asking the same fixed sentence
    every time.

    Parameters
    ----------
    llm_client : ChatClient
    skill_name : str
    request_id : str
    coordinate_timeout : float
    check_in_num : int
        0-indexed check-in round, for prompt context.
    max_check_ins : int

    Returns
    -------
    str
        The question to send. Falls back to a plain, functional
        question if the model returns nothing usable, so a check-in can
        never silently stall on an empty reply.
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
    Decide whether to keep waiting, retry, or ask a follow-up, given the whole check-in conversation so far.

    The multi-turn sibling of `_deliberate` - reasons over the full
    transcript, not just the latest reply, never a keyword match or a
    fixed script.

    Parameters
    ----------
    llm_client : ChatClient
    transcript : list of dict
        ``[{"speaker": "head"|"coordinator", "content": str}, ...]``.
    skill_name : str
    coordinate_timeout : float
    allow_followup : bool
        `False` once `check_in_max_turns` is reached, forcing a real
        decision instead of stalling in a loop.

    Returns
    -------
    dict
        ``{"action": "wait"}``, ``{"action": "retry"}``, or (only when
        `allow_followup`) ``{"action": "followup", "question": str}``.
        Defaults to `"retry"` (the conservative choice) whenever the
        model's answer doesn't clearly parse as one of the allowed
        actions.
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
    """
    Fixed, non-LLM fallback description for a scarlet.

    Parameters
    ----------
    skill : Skill
    params : dict
    name : str

    Returns
    -------
    str
    """
    return f"Scarlet {name!r} backing a {skill.name!r} computation (params={params!r})."


def _compose_scarlet_description(llm_client: ChatClient, skill: Skill, params: dict, name: str) -> str:
    """
    Generate a scarlet's description via real LLM reasoning, not fixed text.

    The description is fed directly into every agent's context window
    (see `scarlets.utils.ScarletUtils.register_scarlet_definition`), so
    this is grounded in the skill's own description/params rather than
    reused verbatim across every invocation, and asks for something
    concrete about the data contract rather than a restatement of what
    the skill does.

    Parameters
    ----------
    llm_client : ChatClient
    skill : Skill
    params : dict
        This invocation's actual parameters.
    name : str
        The scarlet name being described.

    Returns
    -------
    str
        Falls back to `_default_scarlet_description` if the model
        returns nothing usable.
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
    Pre-register every scarlet this attempt's `contribute`/`coordinate` will construct.

    Done before dispatch, on the head, with a real description - rather
    than leaving registration to happen lazily (and blankly) the first
    time some worker constructs its own `ctx.mapper`/`ctx.federator`.
    Names are always assigned deterministically by `run_skill`
    (`mapper_name` is request_id-based, never LLM-authored); only the
    *description* is LLM-generated when `llm_client` is given.

    Parameters
    ----------
    skill : Skill
    params : dict
    mapper_name : str
        This attempt's base scarlet name, passed to `Skill.scarlet_names`.
    llm_client : ChatClient or None
        When given, description generation uses
        `_compose_scarlet_description`; otherwise
        `_default_scarlet_description`.

    Notes
    -----
    A no-op for skills that don't declare any names (`scarlet_names`
    defaults to `[]`).
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



MAX_PLAN_DEPTH = 10


def resolve_refs(value, ns: dict):
    """
    Replace every ``"$name"`` with ``ns["name"]``, recursively.

    Walks dicts and lists so a reference can sit inside a nested structure -
    which is what lets a step pass something like
    ``{"variables": {"s1": "$s1", "n": "$n"}}`` where the outer shape is a
    literal and the leaves are computed values.

    A string that is not exactly ``"$name"`` is left alone, so an expression
    like ``"s2/n - mean**2"`` passes through untouched. An unknown name is
    left as the literal ``"$name"`` rather than raising: the step's own
    schema validation gives a better error than a KeyError here would.
    """
    if isinstance(value, str):
        if value.startswith("$") and value[1:] in ns:
            return ns[value[1:]]
        return value
    if isinstance(value, dict):
        return {k: resolve_refs(v, ns) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_refs(v, ns) for v in value]
    return value


def run_plan(
    compound,
    params: dict,
    config: HarnessConfig,
    buses: Buses,
    on_result: Callable[[dict], None],
    skills: dict,
    on_event: Callable[[dict], None] | None = None,
    depth: int = 0,
    **run_skill_kwargs,
) -> None:
    """
    Execute a `CompoundSkill`'s plan, one step at a time, over a shared namespace.

    The namespace starts as `params` and accumulates each step's declared
    outputs. Steps are advanced by callback rather than by a loop, because
    `run_skill` is non-blocking and delivers through `on_result` - a `for`
    loop would dispatch every step at once.

    Three rules, enforced here and nowhere else:

    RULE 1  always-run - a step with no outputs is a check, not a producer,
            so there is nothing it could already have and it never skips.
    RULE 2  skip - every output the step would produce is already bound.
    RULE 3  abort - a failed step ends the plan, carrying the child's
            ``detail`` and ``retryable`` upward with the step named.
    """
    if depth >= MAX_PLAN_DEPTH:
        on_result({
            "status": "error",
            "detail": f"plan nesting exceeded {MAX_PLAN_DEPTH} levels at {compound.name!r}",
            "retryable": False,
        })
        return

    ns = dict(params)
    steps = list(compound.plan)
    emit = on_event or (lambda _event: None)

    def finish() -> None:
        if isinstance(compound.returns, str):
            on_result({"status": "ok", "result": ns.get(compound.returns),
                       "detail": f"{compound.name}: {len(steps)} step(s)"})
        else:
            out = {"status": "ok", "detail": f"{compound.name}: {len(steps)} step(s)"}
            out.update({field: ns.get(var) for field, var in compound.returns.items()})
            on_result(out)

    def advance(i: int) -> None:
        # Skip forward over anything already satisfied before dispatching.
        while i < len(steps):
            step = steps[i]
            # RULE 1 - always-run. A step with no outputs is a check.
            if not step.produces:
                break
            # RULE 2 - skip. Every output is already bound.
            if all(ns.get(var) is not None for var in step.produces):
                i += 1
                continue
            break

        if i >= len(steps):
            finish()
            return

        step = steps[i]
        emit({"event": "step", "skill": step.skill, "of": compound.name, "index": i})

        if step.skill not in skills:
            on_result({"status": "error",
                       "detail": f"{compound.name!r} plan references unknown skill {step.skill!r}",
                       "retryable": False})
            return

        def then(result: dict) -> None:
            # RULE 3 - abort. Carry the child's retryable upward so an
            # unretryable failure is not retried by whoever called us.
            if result.get("status") != "ok":
                on_result({
                    "status": "error",
                    "detail": f"step {step.skill!r} failed: {result.get('detail')}",
                    "retryable": result.get("retryable", False),
                })
                return
            for var, field in step.produces.items():
                ns[var] = result.get(field)
            advance(i + 1)

        # Ambient namespace first, then this step's own params overlaid with
        # every "$name" resolved from it.
        step_params = {**ns, **resolve_refs(step.params, ns)}
        run_skill(skills[step.skill], step_params, config, buses, then,
                  skills=skills, on_event=on_event, depth=depth + 1,
                  **run_skill_kwargs)

    advance(0)


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
    on_dispatch: Callable[[str, int], None] | None = None,
    skills: dict | None = None,
    on_event: Callable[[dict], None] | None = None,
    depth: int = 0,
) -> None:
    """
    Dispatch one invocation of `skill` across currently-registered workers.

    Does not block and does not return the result - `on_result` fires
    exactly once, on some later thread, with the final result dict
    (shape: ``{"status": "ok"/"error", ...}``), whether that's success,
    a non-retryable failure, or exhausting every retry attempt. Despite
    the module name, nothing here is actually head-specific - it only
    ever touches the `config`/`buses` it's handed, which is exactly what
    lets a worker call this too (see `HarnessContext.invoke_skill`) to
    dispatch a skill across its own peers on its own initiative, with no
    head involvement at all. Workers are discovered fresh via
    `Buses.gather_workers` on every attempt - never a hardcoded
    topology, which is exactly what lets a retry naturally exclude a
    worker that went offline mid-computation.

    A failed attempt is retried (fresh `request_id`, fresh worker
    survey, possibly a new coordinator) only if the result carries
    ``"retryable": True`` - set by a `Skill`'s `coordinate` for failures
    that are plausibly transient. Failures that would just happen again
    regardless of which worker runs them are not retryable, and skills
    that don't set the flag at all default to not-retryable. "no worker
    currently reports this capability" is a precondition check before
    any dispatch happens, not a mid-computation failure, so it is never
    retried here.

    Deliberation (optional, via `dialogue`/`llm_client`): a plain
    timeout normally means an immediate, mechanical retry. When both are
    given, a timeout instead starts a real check-in conversation with
    the coordinator, grounded in the coordinator's own real state.
    Neither side of that conversation is fixed text -
    `_compose_checkin_question` writes the opening question,
    `_deliberate_or_followup` weighs the exchange and decides to wait,
    retry, or ask a genuine follow-up. Bounded on three axes so this can
    never hang: `max_check_ins` caps check-ins per attempt,
    `check_in_max_turns` caps question/answer rounds within one
    check-in, `check_in_timeout` bounds the whole check-in exchange.

    Parameters
    ----------
    skill : Skill
    params : dict
        This invocation's parameters.
    config : HarnessConfig
    buses : Buses
    on_result : callable
        ``(result: dict) -> None``, fired exactly once.
    max_attempts : int or None, optional
        Defaults to `config.max_attempts` when `None`.
    reply_slack : float or None, optional
        Extra seconds beyond the coordinator's own `coordinate_timeout`
        that the head waits for a reply before giving up on an attempt -
        accounts for message round-trip time on top of the
        coordinator's internal deadline. Defaults to
        `config.reply_slack` when `None`.
    dialogue : AgentDialogue or None, optional
        See "Deliberation" above. Omit (with `llm_client`) for the old,
        purely mechanical retry-on-timeout behavior.
    llm_client : ChatClient or None, optional
    max_check_ins : int or None, optional
        Defaults to `config.max_check_ins` when `None`. Only matters
        when `dialogue`/`llm_client` are both given.
    check_in_timeout : float or None, optional
        Defaults to `config.check_in_timeout` when `None`.
    check_in_max_turns : int or None, optional
        Defaults to `config.check_in_max_turns` when `None`.
    """
    # A compound skill is executed, not dispatched. This MUST come before
    # worker resolution below: no worker ever advertises a compound name, so
    # a compound reaching gather_workers() fails instantly with "no online
    # worker currently reports the X capability" - before a single step runs.
    if isinstance(skill, CompoundSkill):
        if skills is None:
            on_result({"status": "error",
                       "detail": f"{skill.name!r} is a compound skill but no skill registry "
                                 f"was passed to run_skill",
                       "retryable": False})
            return
        run_plan(skill, params, config, buses, on_result, skills,
                 on_event=on_event, depth=depth,
                 max_attempts=max_attempts, reply_slack=reply_slack,
                 dialogue=dialogue, llm_client=llm_client,
                 max_check_ins=max_check_ins, check_in_timeout=check_in_timeout,
                 check_in_max_turns=check_in_max_turns)
        return

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
        # Reported before dispatch so a caller can attribute bus traffic to
        # whatever caused this call. A retry mints a *new* request_id here,
        # so one logical invocation can span several - which is exactly why
        # a caller cannot infer the mapping and has to be told it. Failures
        # are swallowed: this is observability, and it must never be able
        # to stop a dispatch.
        if on_dispatch is not None:
            try:
                on_dispatch(request_id, attempt_num)
            except Exception as exc:
                RedisLogger.warning(f"[{config.agent_id}] on_dispatch failed: {exc}")

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
                    # request_id rides along so the whole exchange is
                    # threadable to the dispatch it is about - see
                    # AgentDialogue.start's `context`.
                    dialogue.reply(
                        coordinator, conv_id, question, on_checkin_reply,
                        context={"request_id": request_id},
                    )
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
            conv_id = dialogue.start(
                coordinator, opening_question, on_checkin_reply,
                # Without this an agent_message carries only its own
                # conversation_id, and what it concerns lives solely in
                # this process's memory - a reader would see the head and
                # a worker talking with no way to tell which dispatch
                # prompted it.
                context={"request_id": request_id},
            )

        wait_for_reply()

    attempt(1)


