"""
ConversationStore — thread-safe state that persists across the relay of
threads an async conversation hops through.

Before on_key() (router.py), a function like converse() held its running
state (the message transcript, accumulated results) as local variables
across one blocking call - safe, because one thread's stack owned it for
the whole conversation. Once waiting is callback-based, no single thread's
stack spans the conversation anymore: each leg (dispatch a call, get a
reply, decide the next step) runs on a different, short-lived thread
spawned by a router. Local variables don't survive between those threads -
something has to hold the state in between, and it has to be safe for
concurrent access, since a router could in principle deliver two related
messages to two callback threads close together.

Not Redis-backed, deliberately: this is in-process, per-agent state, same
constraint that already applies to router.py's queues/callbacks - it holds
live Python values (in particular, callables and objects passed through a
conversation), not JSON-serializable data meant to be shared across
processes. See router.py's docstring for the same in-process-only
reasoning applied to callbacks specifically.
"""
import threading


class ConversationStore:
    """
    Thread-safe state that persists across the relay of threads an async conversation hops through.

    Once waiting is callback-based, no single thread's stack spans a
    whole conversation - each leg (dispatch a call, get a reply, decide
    the next step) runs on a different, short-lived thread spawned by a
    router. Local variables don't survive between those threads; this
    holds the state in between, safe for concurrent access.

    Not Redis-backed, deliberately: in-process, per-agent state holding
    live Python values (in particular, callables and objects passed
    through a conversation), not JSON-serializable data meant to be
    shared across processes - same constraint `router.MessageRouter`'s
    queues/callbacks already have.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._state: dict[str, dict] = {}

    def create(self, conversation_id: str, initial: dict) -> None:
        """
        Start tracking a conversation.

        Call once, before the first message is sent - the same
        "register early" discipline `router.MessageRouter` and
        `cancellation.CancellationRegistry` both rely on.

        Parameters
        ----------
        conversation_id : str
        initial : dict
            Initial state, copied (not stored by reference).
        """
        with self._lock:
            self._state[conversation_id] = dict(initial)

    def get(self, conversation_id: str) -> dict | None:
        """
        Snapshot the current state of a conversation.

        Parameters
        ----------
        conversation_id : str

        Returns
        -------
        dict or None
            A copy of the tracked state - callers must use `update`/
            `append` to mutate, not mutate the returned dict. `None` if
            untracked (already forgotten, or never created).
        """
        with self._lock:
            state = self._state.get(conversation_id)
            return dict(state) if state is not None else None

    def update(self, conversation_id: str, **changes) -> None:
        """
        Merge `changes` into the tracked state.

        No-op if the conversation isn't tracked (already forgotten) -
        callers that need to distinguish that from a real update should
        check `get` first.

        Parameters
        ----------
        conversation_id : str
        **changes
            Fields to merge into the tracked state dict.
        """
        with self._lock:
            state = self._state.get(conversation_id)
            if state is not None:
                state.update(changes)

    def append(self, conversation_id: str, key: str, value) -> None:
        """
        Append `value` to a list-valued field, under lock.

        A plain `get` then set from two different threads would race
        (both read the same list before either writes back, one update
        is lost).

        Parameters
        ----------
        conversation_id : str
        key : str
            Field name; created as an empty list if not already present.
        value : object
            Appended to that list.
        """
        with self._lock:
            state = self._state.get(conversation_id)
            if state is not None:
                state.setdefault(key, []).append(value)

    def forget(self, conversation_id: str) -> None:
        """
        Drop tracked state once a conversation is fully done.

        Same cleanup discipline as `router.MessageRouter.forget`, for the
        same reason (`conversation_id`s are minted per conversation,
        never reused).

        Parameters
        ----------
        conversation_id : str
        """
        with self._lock:
            self._state.pop(conversation_id, None)
