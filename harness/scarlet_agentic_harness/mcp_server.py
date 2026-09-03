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

    @mcp.tool()
    async def ask_scarlet_agent(message: str) -> str:
        """
        Ask this scarlet-agents head a question or give it an instruction
        in plain language. It may invoke one or more of its skills
        (currently: median, sum, combine) to answer - real distributed
        dispatch across whatever workers are online right now, not a
        simulation. Returns the final natural-language answer.
        """
        loop = asyncio.get_running_loop()
        done = asyncio.Event()
        box: dict = {}

        def on_done(result, error):
            box["result"] = result
            box["error"] = error
            loop.call_soon_threadsafe(done.set)

        def on_event(event: dict) -> None:
            # Real-time audit trail, same as __main__.py's stdin REPL -
            # goes to stderr since MCP's stdio transport uses stdout for
            # protocol framing.
            print(event, file=sys.stderr)

        head_mod.converse(
            message, config, buses, skills, llm_client, on_done, on_event=on_event, dialogue=dialogue,
        )
        await done.wait()

        if box["error"] is not None:
            raise box["error"]
        return box["result"].answer

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
