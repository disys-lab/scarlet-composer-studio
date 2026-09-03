"""
Unit tests for ConversationStore - no Redis, no subprocess. Covers basic
create/get/update/append/forget, plus a concurrency check: many threads
appending to the same conversation concurrently must not lose updates,
which is exactly the failure mode a plain dict-of-lists without locking
would have (two threads read the same list, both append, one write wins).
"""
import threading

from scarlet_agentic_harness.conversation_store import ConversationStore


def test_create_and_get():
    store = ConversationStore()
    store.create("conv-1", {"messages": []})
    assert store.get("conv-1") == {"messages": []}


def test_get_returns_none_for_untracked_conversation():
    store = ConversationStore()
    assert store.get("does-not-exist") is None


def test_get_returns_a_copy_not_a_live_reference():
    store = ConversationStore()
    store.create("conv-1", {"count": 1})
    snapshot = store.get("conv-1")
    snapshot["count"] = 999
    assert store.get("conv-1") == {"count": 1}


def test_update_merges_changes():
    store = ConversationStore()
    store.create("conv-1", {"count": 1, "status": "pending"})
    store.update("conv-1", status="done")
    assert store.get("conv-1") == {"count": 1, "status": "done"}


def test_update_on_untracked_conversation_is_a_noop():
    store = ConversationStore()
    store.update("does-not-exist", status="done")  # must not raise
    assert store.get("does-not-exist") is None


def test_append_builds_up_a_list_field():
    store = ConversationStore()
    store.create("conv-1", {})
    store.append("conv-1", "messages", "first")
    store.append("conv-1", "messages", "second")
    assert store.get("conv-1") == {"messages": ["first", "second"]}


def test_forget_removes_tracked_state():
    store = ConversationStore()
    store.create("conv-1", {"count": 1})
    store.forget("conv-1")
    assert store.get("conv-1") is None


def test_concurrent_appends_do_not_lose_updates():
    store = ConversationStore()
    store.create("conv-1", {})
    n_threads = 20
    per_thread = 25

    def worker(i):
        for j in range(per_thread):
            store.append("conv-1", "messages", f"{i}-{j}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    messages = store.get("conv-1")["messages"]
    assert len(messages) == n_threads * per_thread
    assert len(set(messages)) == n_threads * per_thread  # no duplicates, none lost
