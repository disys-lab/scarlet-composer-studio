# LLM / MCP Integration

`Messenger.AsTools()` exports any `Messenger` bus as a set of MCP-compatible tool definitions. This lets LLM frameworks interact with distributed agents using the same tool-call interface they already use for databases, APIs, and code execution.

---

## AsTools() Overview

```python
from scarlets.messaging import Messenger

bus = Messenger("quickstart_headagent", agentId="llm_orchestrator")
tool_defs, handlers = bus.AsTools()
```

`AsTools()` returns:

| Return | Type | Contents |
|---|---|---|
| `tool_defs` | `list[dict]` | MCP-spec tool definitions (name, description, inputSchema) |
| `handlers` | `dict[str, callable]` | `{tool_name: callable}` — invoke to execute the tool |

### Available tools

| Tool name | Description |
|---|---|
| `send_message` | Send a message to a named agent on the bus |
| `check_inbox` | Read one pending message from the calling agent's inbox |
| `broadcast` | Send a message to all agents registered on the bus |
| `report_status` | Write a status record to the liveness registry |
| `gather_status` | Return the status of all agents currently online |

---

## Integration with LangChain

```python
from langchain_anthropic import ChatAnthropic
from langchain.tools import StructuredTool
from scarlets.messaging import Messenger

bus = Messenger("quickstart_headagent", agentId="llm_orchestrator")
tool_defs, handlers = bus.AsTools()

# Wrap each handler as a LangChain StructuredTool
lc_tools = []
for td in tool_defs:
    name    = td["name"]
    handler = handlers[name]
    lc_tools.append(
        StructuredTool.from_function(
            func=handler,
            name=name,
            description=td["description"],
        )
    )

llm   = ChatAnthropic(model="claude-sonnet-4-6").bind_tools(lc_tools)
reply = llm.invoke("Check which agents are online and send a ping to each of them.")
```

---

## Integration with Open WebUI (MCP)

Open WebUI supports native MCP server connections. You can wrap a Messenger as a minimal FastMCP server:

```python
# mcp_server.py
import asyncio
from mcp.server.fastmcp import FastMCP
from scarlets.messaging import Messenger

mcp = FastMCP("scarlet-quickstart")
bus = Messenger("quickstart_headagent", agentId="mcp_bridge")
_, handlers = bus.AsTools()

@mcp.tool()
def send_message(target: str, body: dict) -> dict:
    """Send a message to an agent on the quickstart head bus."""
    return handlers["send_message"](target=target, body=body)

@mcp.tool()
def gather_status() -> dict:
    """Return the status of all agents on the quickstart head bus."""
    return handlers["gather_status"]()

if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=8090)
```

Then add `http://localhost:8090/sse` as an MCP server in Open WebUI settings.

---

## Direct Tool-Call Loop (no framework)

```python
import anthropic
from scarlets.messaging import Messenger

bus = Messenger("quickstart_headagent", agentId="llm_agent")
tool_defs, handlers = bus.AsTools()

client = anthropic.Anthropic()

messages = [{"role": "user", "content": "Who is online? Ping hello-agent_local with a greeting."}]

while True:
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        tools=tool_defs,        # pass MCP tool_defs directly
        messages=messages,
    )

    if resp.stop_reason == "end_turn":
        print(resp.content[-1].text)
        break

    # Execute tool calls
    tool_results = []
    for block in resp.content:
        if block.type == "tool_use":
            result = handlers[block.name](**block.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": str(result),
            })

    messages.append({"role": "assistant", "content": resp.content})
    messages.append({"role": "user",      "content": tool_results})
```

---

## Exposing Multiple Buses

LLM agents can hold references to multiple buses and combine their tool defs:

```python
global_bus = Messenger("quickstart_headagent", agentId="llm")
local_bus  = Messenger("quickstart_subagent",  agentId="llm")

global_defs, global_handlers = global_bus.AsTools()
local_defs,  local_handlers  = local_bus.AsTools()

# Prefix tool names to avoid collisions
prefixed_defs = (
    [{**t, "name": f"global_{t['name']}"} for t in global_defs] +
    [{**t, "name": f"local_{t['name']}"} for t in local_defs]
)
prefixed_handlers = (
    {f"global_{k}": v for k, v in global_handlers.items()} |
    {f"local_{k}":  v for k, v in local_handlers.items()}
)
```

---

## Security Note

`send_message` and `broadcast` give the LLM direct write access to agent inboxes. In production:
- Scope the LLM's `agentId` to a non-privileged name (it will appear in all message `"from"` fields)
- Log all LLM-initiated messages with `RedisLogger` for audit trails
- Consider restricting which `target` agent IDs the LLM can address in your wrapper
