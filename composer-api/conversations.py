"""
Reconstruct what the agents actually said to each other, from the messages
Redis already holds.

The Logging page shows `RedisLogger` output: one flat, chronological
stream, ten minutes of retention, and five concurrent requests interleaved
into something no one can follow. This reads the messages themselves and
puts them back into the shape they had - one conversation, the head's
reasoning through it, and the dispatch each decision caused.

─── Where the data is ─────────────────────────────────────────────────────

Every message a `Messenger` sends lands in the recipient's inbox hash,
"<bus>:msg:<agentId>", keyed by sequence number, with two reserved cursor
fields. Nothing deletes a message after it is read - `_ack` only advances a
cursor - so a whole exchange is still there afterwards, until the bus's own
TTL takes it.

Reading those keys directly rather than through `Messenger` is deliberate,
and the same thing harness/tests/transcript.py does for the test suite:
there is no "read someone else's inbox" in the Messenger API, and
constructing a Messenger to look would register this process as an agent on
the bus. All the key-layout knowledge lives in this one module.

─── How a conversation is put back together ───────────────────────────────

Four kinds of message matter, and they join up through two identifiers:

    head_reasoning  conv_id      the head's own trace - narration, tool
                                 calls, results, the final answer. Also
                                 carries "dispatch" events, which are the
                                 only link from a tool call to the
                                 request_id(s) it produced.
    agent_message   request_id   check-in dialogue: the head asking a
                                 coordinator what is happening, in plain
                                 English, and the reply.
    skill_*         request_id   the dispatch envelope - coordinate,
                                 contribute, result, cancel.
    <skill>_ready   request_id   contributor readiness on the local bus.

conv_id groups the conversation. A dispatch event maps call_id ->
request_id, and everything carrying that request_id then belongs under that
call. That mapping cannot be inferred any other way: run_skill mints a
request_id per *attempt*, so one call can span several, and correlating by
timestamp would be wrong the moment two calls overlap - which is the normal
case, since the model routinely issues several tool calls in one turn.

Traffic whose request_id belongs to no known call still gets returned, in
an "unattributed" bucket rather than dropped. That covers a fleet where
PUBLISH_REASONING is off, agents on an older image, and anything dispatched
outside a conversation - all real, and all better shown than hidden.
"""
import json
import logging

from scarlets.utils.ScarletUtils import redisConnect

# Must match harness/scarlet_agentic_harness/reasoning.py. Duplicated rather
# than imported because composer-api does not depend on the harness package -
# they are separate deployables that share only a wire format.
REASONING_SINK = "__head_reasoning__"
REASONING_TYPE = "head_reasoning"

# Reserved fields in an inbox hash; every other field is a sequence number.
_CURSOR_FIELDS = ("__head__", "__tail__")


def _read_bus_messages(r, bus: str) -> list[dict]:
    """
    Every message currently held on `bus`, in send order.

    Returns
    -------
    list of dict
        Each entry is the stored envelope (from/to/seq/ts/body) plus the
        inbox it was read from. Malformed entries are skipped rather than
        failing the whole read - a single bad value should not blind the
        view.
    """
    out: list[dict] = []
    prefix = f"{bus}:msg:"
    for key in r.scan_iter(match=f"{prefix}*"):
        try:
            entries = r.hgetall(key)
        except Exception as exc:
            logging.warning(f"conversations: could not read inbox {key}: {exc}")
            continue
        for field, raw in (entries or {}).items():
            if field in _CURSOR_FIELDS:
                continue
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            msg["_inbox"] = key[len(prefix):]
            msg["_bus"] = bus
            out.append(msg)
    out.sort(key=lambda m: (m.get("ts", 0), m.get("seq", 0)))
    return out


def _classify(msg: dict) -> tuple[str, str | None, str | None]:
    """
    What kind of message this is, and the two ids it can be threaded by.

    Returns
    -------
    (kind, conv_id, request_id)
        `kind` is one of "reasoning", "dialogue", "dispatch", "other".
    """
    body = msg.get("body") or {}
    msg_type = body.get("type")

    if msg_type == REASONING_TYPE:
        return "reasoning", body.get("conv_id"), body.get("request_id")
    if msg_type == "agent_message":
        # request_id is present only when the sender named what the
        # exchange is about (the head does for check-ins). An
        # agent-initiated conversation with no such context still shows,
        # unattributed.
        return "dialogue", None, body.get("request_id")
    if isinstance(msg_type, str) and (msg_type.startswith("skill_") or msg_type.endswith("_ready")):
        return "dispatch", None, body.get("request_id")
    return "other", None, body.get("request_id")


def collect(buses: list[str]) -> dict:
    """
    Read every bus and index the messages by the ids that thread them.

    Parameters
    ----------
    buses : list of str
        Bus names to read. Both the global (head) bus and the local
        (device-group) bus are worth reading: dispatch and check-ins ride
        the former, contributor handshakes the latter, and a failure often
        shows up only in the second.

    Returns
    -------
    dict
        ``{"messages": [...], "by_conv": {...}, "by_request": {...},
        "call_to_requests": {...}}``
    """
    r = redisConnect(decode_responses=True)
    messages: list[dict] = []
    for bus in buses:
        messages.extend(_read_bus_messages(r, bus))
    messages.sort(key=lambda m: (m.get("ts", 0), m.get("seq", 0)))

    by_conv: dict[str, list[dict]] = {}
    by_request: dict[str, list[dict]] = {}
    # call_id -> [request_id, ...]; a retried call has more than one.
    call_to_requests: dict[str, list[str]] = {}
    # request_id -> (conv_id, call_id), learned from dispatch events.
    request_owner: dict[str, tuple[str, str]] = {}

    for msg in messages:
        kind, conv_id, request_id = _classify(msg)
        msg["_kind"] = kind
        if conv_id:
            by_conv.setdefault(conv_id, []).append(msg)
        if request_id:
            by_request.setdefault(request_id, []).append(msg)

        body = msg.get("body") or {}
        if kind == "reasoning" and body.get("event") == "dispatch":
            call_id, rid = body.get("call_id"), body.get("request_id")
            if call_id and rid:
                call_to_requests.setdefault(call_id, [])
                if rid not in call_to_requests[call_id]:
                    call_to_requests[call_id].append(rid)
                if conv_id:
                    request_owner[rid] = (conv_id, call_id)

    return {
        "messages": messages,
        "by_conv": by_conv,
        "by_request": by_request,
        "call_to_requests": call_to_requests,
        "request_owner": request_owner,
    }


def _summarise_result(result) -> str | None:
    """A short, human-readable form of a skill result, for the list view."""
    if not isinstance(result, dict):
        return None
    if result.get("status") == "ok":
        n, value = result.get("n"), result.get("result")
        if value is not None:
            return f"{value}" + (f" over n={n}" if n is not None else "")
        return "ok"
    return result.get("detail") or result.get("status")


def build_conversation(conv_id: str, index: dict) -> dict:
    """
    One conversation, with its dispatch traffic nested under the call that caused it.

    Parameters
    ----------
    conv_id : str
    index : dict
        As returned by `collect`.

    Returns
    -------
    dict
        ``{"conv_id", "question", "answer", "started_at", "ended_at",
        "status", "turns": [...]}`` - `turns` being the reasoning steps in
        order, each `tool_call` carrying the `attempts` it produced and
        each attempt the bus messages belonging to it.
    """
    reasoning = [m for m in index["by_conv"].get(conv_id, []) if m["_kind"] == "reasoning"]
    steps = []
    calls: dict[str, dict] = {}
    question = answer = None

    for msg in reasoning:
        body = msg.get("body") or {}
        event = body.get("event")
        ts = msg.get("ts")

        if event == "tool_call":
            call = {
                "kind": "tool_call", "ts": ts, "call_id": body.get("call_id"),
                "skill": body.get("skill"), "params": body.get("params"),
                "attempts": [], "result": None,
            }
            calls[body.get("call_id")] = call
            steps.append(call)
        elif event == "dispatch":
            call = calls.get(body.get("call_id"))
            attempt = {
                "request_id": body.get("request_id"),
                "attempt": body.get("attempt"),
                "messages": _thread_for_request(body.get("request_id"), index),
            }
            if call is not None:
                call["attempts"].append(attempt)
            else:
                # A dispatch whose tool_call is missing - possible if the
                # inbox has partially expired. Shown on its own rather than
                # silently dropped.
                steps.append({"kind": "orphan_dispatch", "ts": ts, **attempt})
        elif event == "tool_result":
            call = calls.get(body.get("call_id"))
            if call is not None:
                call["result"] = body.get("result")
                call["result_summary"] = _summarise_result(body.get("result"))
        elif event == "question":
            # Surfaced as the conversation's own field rather than as a
            # step: it is what the whole thing is *about*, not something
            # the head did. Left in `turns` as well it renders twice.
            question = body.get("content")
        elif event == "narration":
            steps.append({"kind": "narration", "ts": ts, "content": body.get("content")})
        elif event == "final":
            answer = body.get("content")
            steps.append({"kind": "final", "ts": ts, "content": answer})

    times = [m.get("ts") for m in reasoning if m.get("ts")]
    return {
        "conv_id": conv_id,
        "question": question,
        "answer": answer,
        "started_at": min(times) if times else None,
        "ended_at": max(times) if times else None,
        "status": "answered" if answer is not None else "incomplete",
        "turns": steps,
    }


def _thread_for_request(request_id: str | None, index: dict) -> list[dict]:
    """Every bus message carrying `request_id`, flattened for display."""
    if not request_id:
        return []
    out = []
    for msg in index["by_request"].get(request_id, []):
        body = msg.get("body") or {}
        if body.get("type") == REASONING_TYPE:
            continue  # already represented as a reasoning step
        out.append({
            "ts": msg.get("ts"),
            "from": msg.get("from"),
            "to": msg.get("to"),
            "bus": msg.get("_bus"),
            "type": body.get("type"),
            "kind": msg.get("_kind"),
            # Plain-language check-ins are the readable part; keep the
            # content up front rather than buried in the raw body.
            "content": body.get("content"),
            "body": body,
        })
    return out


def list_conversations(index: dict, limit: int = 50) -> list[dict]:
    """Recent conversations, newest first, summarised for a list view."""
    convs = [build_conversation(cid, index) for cid in index["by_conv"]]
    convs.sort(key=lambda c: c["started_at"] or 0, reverse=True)
    out = []
    for c in convs[:limit]:
        tool_calls = [t for t in c["turns"] if t["kind"] == "tool_call"]
        out.append({
            "conv_id": c["conv_id"],
            "answer": c["answer"],
            "status": c["status"],
            "started_at": c["started_at"],
            "ended_at": c["ended_at"],
            "duration": (c["ended_at"] - c["started_at"])
                        if c["started_at"] and c["ended_at"] else None,
            "skills": [t["skill"] for t in tool_calls],
            "call_count": len(tool_calls),
            # More attempts than calls means something was retried, which
            # is the signal worth surfacing in a list.
            "attempt_count": sum(len(t["attempts"]) for t in tool_calls),
        })
    return out


def unattributed(index: dict) -> list[dict]:
    """
    Dispatch traffic belonging to no conversation we can see.

    Real whenever PUBLISH_REASONING is off, an agent is on an older image,
    or a skill was dispatched outside a conversation. Returned rather than
    dropped - a view that silently hides traffic is worse than one that
    admits it cannot place it.
    """
    owned = set(index["request_owner"])
    out = []
    for request_id, msgs in index["by_request"].items():
        if request_id in owned:
            continue
        times = [m.get("ts") for m in msgs if m.get("ts")]
        out.append({
            "request_id": request_id,
            "started_at": min(times) if times else None,
            "message_count": len(msgs),
            "messages": _thread_for_request(request_id, index),
        })
    out.sort(key=lambda x: x["started_at"] or 0, reverse=True)
    return out
