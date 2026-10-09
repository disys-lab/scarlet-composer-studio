"""
MCP gateway: wraps head.converse() as a single MCP tool, replacing
__main__.py's stdin REPL as the human/external-agent entry point into this
harness's LLM tool-calling loop.

This is a different, higher layer than scarlets' own documented MCP
integration (scarlet-composer-studio's docs/guides/llm-integration.md,
Messenger.AsTools()): that exposes raw bus primitives (send_message,
gather_status, ...) as MCP tools, so an external MCP client's own LLM has
to do its own skill-selection reasoning. This module exposes the already-
built converse() loop instead - one coarse-grained `ask_scarlet_agent`
tool, message in, answer out - so a caller doesn't need to know median/sum/
combine exist at all. Skill selection, dispatch, retry, and deliberation
all still happen inside this harness, using this harness's own LLM
backend, exactly as they do for the stdin REPL - only the entry point
changes.

Requires ROLE=head and a configured LLM backend (LLM_BASE_URL) - there is
no "manual dispatch" fallback here the way __main__.py's stdin branch has
one, since an MCP tool call has no equivalent of a human typing raw JSON
skill invocations by hand.

Run:
    python -m scarlet_agentic_harness.mcp_server

MCP_TRANSPORT selects how a client connects (env var, default "stdio" -
matches __main__.py's local-first default; a real deployment behind
Gustavo would set this to "streamable-http" and expose MCP_PORT):
    stdio            - client launches this process directly (e.g. Claude
                        Desktop's local MCP server config)
    streamable-http  - client connects over HTTP to MCP_HOST:MCP_PORT/mcp
    sse              - legacy HTTP transport, same host/port

Not deployed anywhere yet - see README.md's Status section, same as the
rest of this harness.
"""
import asyncio
import os
import sys

from mcp.server.mcpserver import MCPServer

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.dialogue import AgentDialogue
from scarlet_agentic_harness.llm.client import LLMClient
from scarlet_agentic_harness.skills.registry import discover_skills
from scarlet_agentic_harness import head as head_mod
from scarlet_agentic_harness import reasoning



class _Runtime:
    """
    Per-process dependencies the MCP tool needs.

    `ask_scarlet_agent` has to keep the exact signature ``(message: str) ->
    str``, because MCPServer builds the tool's schema from it - any extra
    parameter would appear as something the caller must supply. So the
    dependencies arrive here instead, set once by `main`, rather than being
    captured by defining the tool inside it.
    """

    def __init__(self, config, buses, skills, llm_client, dialogue):
        self.config = config
        self.buses = buses
        self.skills = skills
        self.llm_client = llm_client
        self.dialogue = dialogue


_RUNTIME: _Runtime | None = None


def _log_event(event: dict) -> None:
    """
    Print one conversation event as a real-time audit trail.

    Goes to stderr: MCP's stdio transport uses stdout for protocol framing.
    """
    print(event, file=sys.stderr)


class _AsyncResultBox:
    """
    Catches `converse`'s completion callback and wakes the awaiting coroutine.

    `converse` finishes on a worker thread, so the event has to be set via
    `call_soon_threadsafe` rather than directly.
    """

    def __init__(self, loop, done):
        self._loop = loop
        self._done = done
        self.result = None
        self.error = None

    def __call__(self, result, error) -> None:
        """Store the outcome and signal the waiting coroutine."""
        self.result = result
        self.error = error
        self._loop.call_soon_threadsafe(self._done.set)


async def ask_scarlet_agent(message: str) -> str:
    """
    Ask this scarlet-agents head a question or give it an instruction
    in plain language. It may invoke one or more of its skills
    (currently: median, sum, combine) to answer - real distributed
    dispatch across whatever workers are online right now, not a
    simulation. Returns the final natural-language answer.
    """
    rt = _RUNTIME
    loop = asyncio.get_running_loop()
    done = asyncio.Event()
    box = _AsyncResultBox(loop, done)

    # Wrapped so the same events also reach the bus, where something other
    # than this process can read them - stderr is visible only to whoever
    # is attached to this container and is gone once the request ends.
    on_event = reasoning.publishing_on_event(rt.buses, inner=_log_event)

    head_mod.converse(
        message, rt.config, rt.buses, rt.skills, rt.llm_client, box,
        on_event=on_event, dialogue=rt.dialogue,
        max_turns=rt.config.converse_max_turns,
    )
    await done.wait()

    if box.error is not None:
        raise box.error
    return box.result.answer


def main() -> None:
    config = HarnessConfig.from_env()
    if config.role != "head":
        raise SystemExit(
            "scarlet_agentic_harness.mcp_server requires ROLE=head - it wraps "
            "converse(), the head-side LLM tool-calling loop, not a worker's "
            "skill dispatch."
        )
    if not config.llm_base_url:
        raise SystemExit(
            "scarlet_agentic_harness.mcp_server requires LLM_BASE_URL - unlike "
            "__main__.py's stdin REPL, there is no manual-dispatch fallback "
            "for an MCP tool call."
        )

    buses = Buses(config)
    skills = discover_skills()
    buses.report_status(capabilities=[])

    llm_client = LLMClient(config)

    # Symmetric with __main__.py's own head-with-LLM branch: the head can
    # also be the *responder* in an agent-initiated conversation (e.g. a
    # coordinator checking in), not just the initiator - see dialogue.py.
    dialogue = AgentDialogue(buses.global_bus, llm_client)
    buses.global_router.default_handler = dialogue.handle

    mcp = MCPServer("scarlet-agents")

    global _RUNTIME
    _RUNTIME = _Runtime(config, buses, skills, llm_client, dialogue)
    mcp.tool()(ask_scarlet_agent)

    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(
            transport=transport,
            host=os.environ.get("MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_PORT", "8090")),
        )


if __name__ == "__main__":
    main()
