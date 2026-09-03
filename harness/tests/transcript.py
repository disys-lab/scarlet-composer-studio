"""
Transcript capture for real-LLM tests - reconstructs every message sent on
a bus directly from Redis, rather than instrumenting/monkeypatching
Messenger.Send() itself.

That distinction matters specifically because workers run as real OS
subprocesses (see helpers.py's spawn_worker) - a monkeypatch in the test
process's own memory would never see a subprocess worker's in-process
Send() calls at all. Redis is the one place every Send(), from every
process, actually lands (scarlets.messaging.Messenger writes each message
as its own key: "<scarletName>:msg:<targetAgentId>:<seq>"), so scanning it
after a run is a complete, process-agnostic record - no code under test
needs to know it's being observed.
"""
import json
from pathlib import Path

from scarlets.utils.ScarletUtils import redisConnect

TRANSCRIPTS_DIR = Path(__file__).resolve().parent.parent / "transcripts"


def capture_transcript(bus_names: dict[str, str]) -> list[dict]:
    """
    bus_names: label -> scarletName, e.g. {"global": head_config.head_bus,
    "local": head_config.device_group}. Returns every message found on any
    of those buses, in send order (by timestamp), each annotated with
    which bus it came from.
    """
    if not bus_names:
        return []  # nothing to scan for - don't even open a Redis connection
    r = redisConnect(decode_responses=True)
    entries: list[dict] = []
    for label, scarlet_name in bus_names.items():
        prefix = f"{scarlet_name}:msg:"
        for key in r.scan_iter(match=f"{prefix}*"):
            remainder = key[len(prefix):]
            parts = remainder.split(":")
            if len(parts) != 2 or parts[0] in ("tail", "head"):
                continue  # cursor key (.../msg/tail/<agentId> or .../msg/head/<agentId>), not a message
            raw = r.get(key)
            if raw is None:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            payload["_bus"] = label
            payload["_redis_key"] = key
            entries.append(payload)
    entries.sort(key=lambda m: (m.get("ts", 0), m.get("seq", 0)))
    return entries


def format_transcript_markdown(title: str, entries: list[dict]) -> str:
    """Standalone rendering (title + body) - used when there's no LLM
    conversation to render alongside (see write_transcript(), which
    composes format_transcript_markdown_body() into a larger document
    instead of calling this)."""
    return f"# {title}\n\n{format_transcript_markdown_body(entries)}"


def format_transcript_markdown_body(entries: list[dict]) -> str:
    lines = [f"{len(entries)} message(s) captured, in send order.", ""]
    if not entries:
        lines.append("_No messages were found on the scanned buses._")
        return "\n".join(lines)

    for i, m in enumerate(entries, 1):
        body = m.get("body", {})
        msg_type = body.get("type", "?")
        lines.append(f"### {i}. `{m.get('from', '?')}` → `{m.get('to', '?')}` — `{msg_type}` ({m.get('_bus')} bus)")
        lines.append("")
        lines.append(f"- timestamp: `{m.get('ts')}`")
        lines.append(f"- seq: `{m.get('seq')}`")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(body, indent=2, default=str))
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def format_llm_conversation_markdown(messages: list[dict]) -> str:
    """
    Renders converse()'s retained .messages (the canonical LLM conversation
    shape - see head.py/llm/client.py) - this is the head's own reasoning
    trace (what it was asked, what it decided to call, what it was told,
    what it said back), never touches Redis at all, so capture_transcript()
    can't see it - it's a direct HTTP exchange with the LLM backend.
    """
    lines = ["## LLM conversation (head's own reasoning trace)", ""]
    for i, m in enumerate(messages):
        role = m.get("role", "?")
        if role == "tool":
            lines.append(f"**{i}. tool result** (call `{m.get('tool_call_id')}`)")
            lines.append("```json")
            lines.append(json.dumps(m.get("content"), indent=2, default=str))
            lines.append("```")
        else:
            lines.append(f"**{i}. {role}**")
            if m.get("content"):
                lines.append(f"> {m['content']}")
            for tc in m.get("tool_calls") or []:
                lines.append(f"- tool call: `{tc['name']}({json.dumps(tc['arguments'])})`")
        lines.append("")
    return "\n".join(lines)


def write_transcript(
    test_name: str, bus_names: dict[str, str], llm_messages: list[dict] | None = None, extra_notes: str = "",
) -> Path:
    """Capture + format + write to transcripts/<test_name>.md. Returns the
    path written, for the caller to report/attach. llm_messages, if given
    (e.g. converse()'s result.messages), is rendered as its own section
    ahead of the bus-level trace - the head's own LLM reasoning isn't bus
    traffic and capture_transcript() can't see it on its own."""
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    sections = [f"# Transcript: {test_name}", ""]
    if llm_messages is not None:
        sections.append(format_llm_conversation_markdown(llm_messages))
        sections.append("---")
        sections.append("")
    entries = capture_transcript(bus_names)
    sections.append("## Distributed bus traffic (head/coordinator/worker messages)")
    sections.append("")
    sections.append(format_transcript_markdown_body(entries))
    body = "\n".join(sections)
    if extra_notes:
        body += f"\n---\n\n{extra_notes}\n"
    path = TRANSCRIPTS_DIR / f"{test_name}.md"
    path.write_text(body)
    return path
