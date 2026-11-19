"""Dispatching one skill to its workers, with retries and coordinator check-ins."""
import threading
import uuid

from scarlets.utils.RedisLogger import RedisLogger

from scarlet_agentic_harness.context import HarnessContext


class CheckIn:
    """
    One check-in round: ask a silent coordinator what is happening.

    Two independent things can end a round - the coordinator's conversation
    reaches a decision, or `check_in_timeout` expires (which bounds the
    *whole* exchange including follow-ups). Only one may act, whichever
    arrives first, which is what `_resolve_once` enforces.

    Both the opening question and every follow-up are composed by a real
    LLM call grounded in the conversation so far, not fixed text, so the
    exchange can go where the coordinator's answer leads within
    `check_in_max_turns`.

    Parameters
    ----------
    attempt : SkillAttempt
        The attempt this round belongs to.
    check_in_num : int
        Zero-based round number.
    """

    def __init__(self, attempt, check_in_num: int):
        self._attempt = attempt
        self._check_in_num = check_in_num
        self._resolved = False
        self._lock = threading.Lock()
        self._transcript: list[dict] = []
        self._turns_used = 0
        self._conv_id = None

    def start(self) -> None:
        """Arm the timeout, then open the conversation with the coordinator."""
        d = self._attempt.dispatch
        RedisLogger.info(
            f"[{d.config.agent_id}] {d.skill.name!r} request={self._attempt.request_id} "
            f"coordinator {self._attempt.coordinator!r} has not replied - checking in "
            f"(round {self._check_in_num + 1}/{d.max_check_ins})")

        timer = threading.Timer(d.check_in_timeout, self._on_timeout)
        timer.daemon = True
        timer.start()

        # Imported here to keep this module free of a cycle through dispatch.
        from scarlet_agentic_harness.dispatch import _compose_checkin_question
        opening = _compose_checkin_question(
            d.llm_client, d.skill.name, self._attempt.request_id,
            d.skill.coordinate_timeout, self._check_in_num, d.max_check_ins)
        self._transcript.append({"speaker": "head", "content": opening})
        self._turns_used += 1
        self._conv_id = d.dialogue.start(
            self._attempt.coordinator, opening, self._on_reply,
            # Without this an agent_message carries only its own
            # conversation_id, and what it concerns lives solely in this
            # process's memory - a reader would see the head and a worker
            # talking with no way to tell which dispatch prompted it.
            context={"request_id": self._attempt.request_id})

    def _resolve_once(self, action) -> None:
        """Run `action` only if nothing has already resolved this round."""
        with self._lock:
            if self._resolved:
                return
            self._resolved = True
        action()

    def _on_timeout(self) -> None:
        """The coordinator never answered the check-in either."""
        d = self._attempt.dispatch
        RedisLogger.info(
            f"[{d.config.agent_id}] {d.skill.name!r} request={self._attempt.request_id} "
            f"coordinator {self._attempt.coordinator!r} did not answer the check-in itself")
        self._resolve_once(lambda: self._attempt.handle({
            "status": "error",
            "detail": "coordinator did not respond in time (unresponsive to check-in)",
            "retryable": True,
        }))

    def _on_reply(self, content: str, sender: str) -> None:
        """Decide from the coordinator's answer: follow up, wait, or retry."""
        from scarlet_agentic_harness.dispatch import _deliberate_or_followup
        d = self._attempt.dispatch
        self._transcript.append({"speaker": "coordinator", "content": content})
        allow_followup = self._turns_used < d.check_in_max_turns
        decision = _deliberate_or_followup(
            d.llm_client, self._transcript, d.skill.name,
            d.skill.coordinate_timeout, allow_followup)
        RedisLogger.info(
            f"[{d.config.agent_id}] {d.skill.name!r} request={self._attempt.request_id} "
            f"check-in reply from {sender!r}: {content!r} - decision: {decision}")

        if decision["action"] == "followup":
            self._turns_used += 1
            question = decision["question"]
            self._transcript.append({"speaker": "head", "content": question})
            # request_id rides along so the whole exchange is threadable to
            # the dispatch it is about - see AgentDialogue.start's `context`.
            d.dialogue.reply(self._attempt.coordinator, self._conv_id, question,
                             self._on_reply,
                             context={"request_id": self._attempt.request_id})
        elif decision["action"] == "wait":
            self._resolve_once(self._attempt.wait_for_reply)
        else:
            self._resolve_once(lambda: self._attempt.handle({
                "status": "error",
                "detail": (f"coordinator did not respond in time (checked in, "
                           f"decided to retry: {content!r})"),
                "retryable": True,
            }))


class SkillAttempt:
    """
    One attempt at dispatching a skill: pick workers, send, await the reply.

    A retry is a *new* attempt with a new request_id, not a re-send, which
    is why per-attempt state lives here rather than on `SkillDispatch`:
    cancelling a superseded attempt has to reach exactly that attempt's
    workers.

    Parameters
    ----------
    dispatch : SkillDispatch
        Everything shared across attempts.
    attempt_num : int
        One-based.
    """

    def __init__(self, dispatch, attempt_num: int):
        self.dispatch = dispatch
        self.attempt_num = attempt_num
        self.request_id = str(uuid.uuid4())
        self.workers: list[str] = []
        self.coordinator = None
        self.request: dict | None = None

    def run(self) -> None:
        """Select workers, register scarlets, dispatch, and start waiting."""
        from scarlet_agentic_harness.dispatch import _register_scarlets
        d = self.dispatch

        workers_info = d.buses.gather_workers()
        self.workers = [w for w, rec in workers_info.items()
                        if d.skill.name in rec.get("capabilities", [])]
        if not self.workers:
            d.on_result({"status": "error",
                         "detail": (f"no online worker currently reports the "
                                    f"{d.skill.name!r} capability")})
            return

        # Reported before dispatch so a caller can attribute bus traffic to
        # whatever caused this call. A retry mints a *new* request_id, so one
        # logical invocation can span several - which is why a caller cannot
        # infer the mapping and has to be told. Failures are swallowed: this
        # is observability and must never stop a dispatch.
        if d.on_dispatch is not None:
            try:
                d.on_dispatch(self.request_id, self.attempt_num)
            except Exception as exc:
                RedisLogger.warning(f"[{d.config.agent_id}] on_dispatch failed: {exc}")

        self.coordinator = d.skill.coordinator_for(d.ctx, self.workers)
        self.request = request = {
            "request_id": self.request_id,
            "skill": d.skill.name,
            "mapper_name": f"{d.skill.name}_{self.request_id}",
            "coordinator": self.coordinator,
            "workers": self.workers,
            "params": d.params,
        }

        # Register before dispatch, not after - see _register_scarlets()'s
        # docstring. A blocking Redis write, so it lands before any worker can
        # construct its own blank-description Mapper/Federator in response to
        # the Send below.
        _register_scarlets(d.skill, d.params, request["mapper_name"], d.llm_client)

        RedisLogger.info(
            f"[{d.config.agent_id}] dispatching {d.skill.name!r} "
            f"request={self.request_id} attempt={self.attempt_num} "
            f"coordinator={self.coordinator} workers={self.workers}")
        for worker_id in self.workers:
            msg_type = ("skill_coordinate" if worker_id == self.coordinator
                        else "skill_contribute")
            d.buses.global_bus.Send(worker_id, {"type": msg_type, **request})

        if self.coordinator == d.config.agent_id:
            # Only reached if a skill overrides coordinator_for() to return
            # the invoking agent's own id. Still on a new thread rather than
            # inline, so run_skill never blocks its own caller.
            threading.Thread(target=self._coordinate_locally, daemon=True).start()
            return

        self.wait_for_reply()

    def _coordinate_locally(self) -> None:
        """Thread body for the rare self-coordinating case."""
        d = self.dispatch
        # The same request object that was dispatched, not a rebuilt copy.
        self.handle(d.skill.coordinate(d.ctx, self.request, self.workers))

    def wait_for_reply(self) -> None:
        """Arm the router for this attempt's reply, with a timeout."""
        d = self.dispatch
        # No explicit forget() needed - on_key()'s callback/timeout pair is
        # self-cleaning either way it resolves (see router.py).
        d.buses.global_router.on_key(
            self.request_id, self._on_reply,
            timeout=d.skill.coordinate_timeout + d.reply_slack,
            on_timeout=lambda: self.on_timeout(0))

    def _on_reply(self, msg: dict) -> None:
        """Unwrap the bus message and hand its body to `handle`."""
        self.handle(msg.get("body", {}))

    def on_timeout(self, check_in_num: int) -> None:
        """
        The coordinator went quiet: check in, or give up and let `handle` retry.

        Parameters
        ----------
        check_in_num : int
            Zero-based; `max_check_ins` rounds are allowed before this stops
            asking and reports a plain timeout.
        """
        d = self.dispatch
        if (d.dialogue is None or d.llm_client is None
                or check_in_num >= d.max_check_ins):
            self.handle({"status": "error",
                         "detail": "coordinator did not respond in time",
                         "retryable": True})
            return
        CheckIn(self, check_in_num).start()

    def handle(self, result: dict) -> None:
        """
        Finish, or cancel this attempt's workers and start the next one.

        Parameters
        ----------
        result : dict
            A skill result. Non-ok and retryable, with attempts remaining,
            means retry; anything else is final.
        """
        d = self.dispatch
        if result.get("status") == "ok":
            RedisLogger.info(f"[{d.config.agent_id}] {d.skill.name!r} "
                             f"request={self.request_id} succeeded")
            d.on_result(result)
            return
        if not result.get("retryable", False) or self.attempt_num >= d.max_attempts:
            RedisLogger.info(
                f"[{d.config.agent_id}] {d.skill.name!r} request={self.request_id} "
                f"failed permanently: {result.get('detail')}")
            d.on_result(result)
            return
        RedisLogger.info(
            f"[{d.config.agent_id}] {d.skill.name!r} request={self.request_id} "
            f"failed (retryable): {result.get('detail')} - retrying as attempt "
            f"{self.attempt_num + 1}")
        for worker_id in self.workers:
            d.buses.global_bus.Send(worker_id, {"type": "skill_cancel",
                                                "request_id": self.request_id})
        d.attempt(self.attempt_num + 1)


class SkillDispatch:
    """
    Everything one `run_skill` call needs, shared across its attempts.

    Parameters
    ----------
    skill : Skill
    params : dict
    config : HarnessConfig
    buses : Buses
    on_result : callable
        Called exactly once with the final result.
    max_attempts, reply_slack, max_check_ins, check_in_timeout,
    check_in_max_turns : int or float
        Already resolved against `config` by `run_skill`.
    dialogue : AgentDialogue or None
    llm_client : ChatClient or None
        Both are required for check-ins; without them a timeout goes
        straight to a retry.
    on_dispatch : callable or None
    """

    def __init__(self, skill, params, config, buses, on_result, max_attempts,
                 reply_slack, dialogue, llm_client, max_check_ins,
                 check_in_timeout, check_in_max_turns, on_dispatch):
        self.skill = skill
        self.params = params
        self.config = config
        self.buses = buses
        self.on_result = on_result
        self.max_attempts = max_attempts
        self.reply_slack = reply_slack
        self.dialogue = dialogue
        self.llm_client = llm_client
        self.max_check_ins = max_check_ins
        self.check_in_timeout = check_in_timeout
        self.check_in_max_turns = check_in_max_turns
        self.on_dispatch = on_dispatch
        self.ctx = HarnessContext(config, buses)

    def run(self) -> None:
        """Start the first attempt."""
        self.attempt(1)

    def attempt(self, attempt_num: int) -> None:
        """Run attempt `attempt_num`, one-based."""
        SkillAttempt(self, attempt_num).run()
