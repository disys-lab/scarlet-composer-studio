# Scarlet Declarations

`#scarlet` declarations let you describe scarlets directly in your agent source code — without requiring the agent to be running. The `ScarletInterpreter` reads `.py` files and extracts these declarations to populate the Composer UI's Scarlets tab and the Redis scarlet definition registry.

---

## Syntax

```python
# Single-line declaration
#scarlet Mapper gradient_bus "Collects per-worker numpy gradients. Key: {NODE_ADDRESS}."

# Multi-line declaration with attributes
#scarlet Messenger task_bus "Head-to-worker task dispatch channel."
#scarlet+ description: Carries task dicts of form {task, model, data}. Workers reply on the same bus.
#scarlet+ bus: quickstart_headagent
```

Declarations are comments — they have no runtime effect on Python execution.

---

## Token Grammar

```
#scarlet <type> <name> ["<description>"]
#scarlet+ <attribute>: <value>
```

| Token | Required | Values |
|---|---|---|
| `type` | Yes | `Mapper`, `Federator`, `Messenger`, `RedisScarlet` |
| `name` | Yes | Any string, no spaces |
| `description` | No | Quoted string on the same line as `#scarlet` |
| `#scarlet+` | No | One or more continuation lines. Each is `key: value`. |

Continuation lines (`#scarlet+`) must immediately follow the opening `#scarlet` line with no blank lines between them.

---

## Parsing

`ScarletInterpreter.interpret_file(path)` uses Python's `tokenize` module to walk the token stream. It is **not eval-based** — it reads comment tokens only and extracts declarations without executing any code.

```python
from scarletcomposer.interpreter.ScarletInterpreter import ScarletInterpreter

si = ScarletInterpreter()
scarlets = si.interpret_file("agents/hello_agent.py")
# Returns list of dicts: [{"type": "Mapper", "name": "gradient_bus", "description": "..."}, ...]
```

The Composer UI calls this automatically when you click **Load from file** on the Scarlets tab.

---

## Full Example

```python
#!/usr/bin/env python3
"""
Hello Agent — quickstart example for Scarlet Composer Studio.
"""

#scarlet Messenger quickstart_headagent "Global coordination bus for the quickstart campaign."
#scarlet+ description: Head dispatches tasks here. Workers reply on the same bus. agentId: {APP_ID}_{NODE_ADDRESS}.
#scarlet+ bus: quickstart_headagent

#scarlet Messenger quickstart_subagent "Intra-group peer bus for quickstart workers."
#scarlet+ description: Direct worker-to-worker communication. Head does not monitor this bus.
#scarlet+ bus: quickstart_subagent

#scarlet Mapper quickstart_heartbeats "Heartbeat map — each worker writes its status every 60 s."
#scarlet+ description: Values are dicts with keys: status, last_seen, capabilities. Key: {NODE_ADDRESS}.

import os
import time
from scarlets.messaging import Messenger

APP_ID       = os.environ.get("APP_ID", "quickstart")
NODE         = os.environ.get("NODE_ADDRESS", "local")
HEAD_BUS     = os.environ.get("HEAD_BUS",     f"{APP_ID}_headagent")
DEVICE_GROUP = os.environ.get("DEVICE_GROUP", f"{APP_ID}_subagent")
AGENT_ID     = f"{APP_ID}_{NODE}"

global_bus = Messenger(HEAD_BUS,     agentId=AGENT_ID)
local_bus  = Messenger(DEVICE_GROUP, agentId=AGENT_ID)
```

---

## Composer UI Integration

On the **Scarlets** tab in the Composer UI:

1. Enter the path to your agent file in the **Load from file** field.
2. Click **Load** — the `ScarletInterpreter` parses the file and displays all declared scarlets.
3. Click **Register** next to any scarlet to write its definition to Redis.

Once registered, the scarlet appears in the Scarlets list alongside runtime-discovered ones (written by agents as they instantiate primitives).

---

## Relationship to Runtime Self-Registration

At runtime, every `Mapper`/`Messenger` constructor calls `register_scarlet_definition` automatically:

```python
# Inside Mapper.__init__:
self.register_scarlet_definition(
    scarlet_type="Mapper",
    description=description,
    overwrite=False,    # first caller wins
)
```

`#scarlet` declarations complement this — they allow pre-registration before any agent is running, and they allow richer descriptions than what the constructor receives.

If both exist, the runtime registration wins only if `overwrite=True` is passed explicitly. The default (`overwrite=False`) means the first registration (usually from the UI or the head agent) is preserved.
