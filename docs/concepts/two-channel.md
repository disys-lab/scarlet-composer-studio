# Two-Channel Architecture

Every agent in Scarlet Composer Studio opens exactly two Messenger buses. This is not a convention — it reflects the physical structure of most distributed agent deployments.

---

## The Pattern

```python
HEAD_BUS     = os.environ.get("HEAD_BUS", f"{APP_ID}_headagent")
DEVICE_GROUP = os.environ.get("DEVICE_GROUP", f"{APP_ID}_subagent")
AGENT_ID     = f"{APP_ID}_{NODE_ADDRESS}"

global_bus = Messenger(HEAD_BUS,     agentId=AGENT_ID)   # campaign coordination
local_bus  = Messenger(DEVICE_GROUP, agentId=AGENT_ID)   # intra-group communication
```

| Bus | Name | Who subscribes | Used for |
|---|---|---|---|
| `global_bus` | `{APP_ID}_headagent` | All agents in the campaign | Task dispatch from head, heartbeats, capability discovery |
| `local_bus` | `{APP_ID}_subagent` | Agents in the same device group | Peer communication without involving the head |

---

## Why Two Buses?

Consider a factory deployment with 20 sensor nodes spread across 4 production lines.

**Single bus (naive approach):**
Every message from any node goes to every other node. A head agent broadcasting a configuration update hits all 20 workers simultaneously — fine. But a worker on Line 1 wanting to ask a peer on Line 1 about its sensor reading has to use the same bus and wait for any head-agent polling.

**Two buses:**
```
global_bus ("factory_headagent")
  ↕ head agent ↔ all 20 workers

local_bus ("line1_subagent")
  ↕ 5 workers on Line 1 ↔ each other

local_bus ("line2_subagent")
  ↕ 5 workers on Line 2 ↔ each other
```

The head sees everything via the global bus. Workers communicate locally without routing through the head. Coordination overhead scales with the number of groups, not the number of workers.

---

## Message Routing

When a worker receives a message it echoes the reply on the same bus it received from:

```python
def handle_message(msg, source_bus_name):
    sender = msg.get("from")
    reply_bus = global_bus if source_bus_name == HEAD_BUS else local_bus
    reply_bus.Send(sender, {"result": ..., "channel": source_bus_name})
```

This means:
- Tasks dispatched from the head via `global_bus` get replies on `global_bus`.
- Local peer messages get replies on `local_bus`.
- The head never needs to monitor the local bus.

---

## Bus-Scoped Counters

The Messenger key schema scopes all counters to the bus namespace:

```
{scarletName}:msg:tail:{agentId}
{scarletName}:msg:head:{agentId}
```

A worker with `agentId = "factory_osu1"` opening both buses has:
- `factory_headagent:msg:tail:factory_osu1` — sequence counter for global inbox
- `line1_subagent:msg:tail:factory_osu1` — sequence counter for local inbox

These are completely independent. Receiving on the global bus does not advance the cursor on the local bus. The same agent can safely participate in multiple campaign buses simultaneously.

---

## HEAD_BUS Override

By default, workers derive the global bus name from their `APP_ID`:

```python
HEAD_BUS = os.environ.get("HEAD_BUS", f"{APP_ID}_headagent")
# APP_ID=quickstart → HEAD_BUS="quickstart_headagent"
```

Setting `HEAD_BUS` explicitly enables a shared head agent that manages multiple campaigns — see [Campaign Isolation](campaigns.md#pattern-b-shared-head).

---

## Example: hello-agent

The quickstart `hello_agent.py` demonstrates this pattern in full:

```python
APP_ID       = os.environ.get("APP_ID", "quickstart")
NODE         = os.environ.get("NODE_ADDRESS", "local")
DEVICE_GROUP = os.environ.get("DEVICE_GROUP", f"{APP_ID}_subagent")
AGENT_ID     = f"{APP_ID}_{NODE}"
HEAD_BUS     = os.environ.get("HEAD_BUS", f"{APP_ID}_headagent")

global_bus = Messenger(HEAD_BUS,     agentId=AGENT_ID)
local_bus  = Messenger(DEVICE_GROUP, agentId=AGENT_ID)

# Report capabilities on both buses at startup
capabilities = {
    "status": "online", "capabilities": ["echo", "heartbeat"],
    "device_group": DEVICE_GROUP, "head_bus": HEAD_BUS,
}
global_bus.ReportStatus(capabilities)
local_bus.ReportStatus(capabilities)

# Poll both buses in a tight loop
while True:
    msg = global_bus.Receive(timeout=1)
    if msg: handle_message(msg, HEAD_BUS)

    msg = local_bus.Receive(timeout=1)
    if msg: handle_message(msg, DEVICE_GROUP)

    time.sleep(0.05)
```
