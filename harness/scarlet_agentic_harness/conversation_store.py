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
    def __init__(self):
        self._lock = threading.Lock()
        self._state: dict[str, dict] = {}

    def create(self, conversation_id: str, initial: dict) -> None:
        """Start tracking a conversation. Call once, before the first
        message is sent - the same "register early" discipline router.py
        and the cancellation registry both rely on."""
        with self._lock:
            self._state[conversation_id] = dict(initial)

    def get(self, conversation_id: str) -> dict | None:
        """Snapshot of current state, or None if untracked (already
        forgotten, or never created). Returns a copy - callers must use
        update()/append() to mutate, not mutate the returned dict."""
        with self._lock:
            state = self._state.get(conversation_id)
            return dict(state) if state is not None else None

    def update(self, conversation_id: str, **changes) -> None:
        """Merge `changes` into the tracked state. No-op if the
        conversation isn't tracked (already forgotten) - callers that need
        to distinguish that from a real update should check get() first."""
        with self._lock:
            state = self._state.get(conversation_id)
            if state is not None:
                state.update(changes)

    def append(self, conversation_id: str, key: str, value) -> None:
        """Append `value` to a list-valued field under lock - a plain
        get() then set() from two different threads would race (both read
        the same list before either writes back, one update is lost)."""
        with self._lock:
            state = self._state.get(conversation_id)
            if state is not None:
                state.setdefault(key, []).append(value)

    def forget(self, conversation_id: str) -> None:
        """Drop tracked state once a conversation is fully done - same
        cleanup discipline as router.py's forget(), for the same reason
        (conversation_ids are minted per conversation, never reused)."""
        with self._lock:
            self._state.pop(conversation_id, None)
