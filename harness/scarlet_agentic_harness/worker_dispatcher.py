"""Routes one inbound bus message to the right worker-side handler."""
import threading

from scarlets.utils.RedisLogger import RedisLogger


class WorkerDispatcher:
    """
    The worker's `default_handler`: turns a bus message into local work.

    Callable with one message, so it drops straight into
    `global_router.default_handler`. Skill work runs on its own thread -
    the handler itself must return promptly or the router stops reading the
    bus.

    Unrecognised types, and `agent_message` with no dialogue configured,
    are dropped: that matches prior behaviour for anything nobody is set up
    to handle.

    Parameters
    ----------
    config : HarnessConfig
    buses : Buses
    skills : dict
        Skill name -> instance.
    registry : CancellationRegistry
        Issues the token for each request and forgets it when done.
    llm_client : ChatClient or None
    data_profiles : dict
    dialogue : AgentDialogue or None
    """

    def __init__(self, config, buses, skills, registry, llm_client,
                 data_profiles, dialogue):
        self._config = config
        self._buses = buses
        self._skills = skills
        self._registry = registry
        self._llm_client = llm_client
        self._data_profiles = data_profiles
        self._dialogue = dialogue

    def __call__(self, msg: dict) -> None:
        """Dispatch one message by its ``type``."""
        body = msg.get("body", {})
        msg_type = body.get("type")
        request_id = body.get("request_id")

        if msg_type in ("skill_contribute", "skill_coordinate"):
            token = self._registry.create(request_id,
                                          skill_name=body.get("skill", ""))
            RedisLogger.info(
                f"[{self._config.agent_id}] started {msg_type} for "
                f"skill={body.get('skill')!r} request={request_id}")
            threading.Thread(target=self._run, args=(msg, token, request_id),
                             daemon=True).start()
        elif msg_type == "skill_cancel":
            RedisLogger.info(f"[{self._config.agent_id}] received skill_cancel "
                             f"for request={request_id}")
            self._registry.cancel(request_id)
        elif msg_type == "agent_message" and self._dialogue is not None:
            self._dialogue.handle(msg)

    def _run(self, msg: dict, token, request_id) -> None:
        """Thread body: handle the message, then always release the token."""
        # Imported here rather than at module scope: worker.py imports this
        # class, so a top-level import would be circular.
        from scarlet_agentic_harness.worker import handle_message
        try:
            handle_message(msg, self._config, self._buses, self._skills, token,
                           llm_client=self._llm_client,
                           data_profiles=self._data_profiles,
                           dialogue=self._dialogue)
        finally:
            self._registry.forget(request_id)
