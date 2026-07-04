# Quickstart — Docker Compose

Stand up a complete Scarlet deployment on a single machine in under 5 minutes.

!!! tip "What you'll get"
    A Scarlet Composer UI and a live `hello-agent` that listens on two Messenger buses and echoes messages back. All wired together with `docker compose up` against an external Redis instance.

---

## Prerequisites

- Docker Engine 24+ and Docker Compose v2
- A Redis 6+ instance with AUTH enabled
- Pull access to `ghcr.io/disys-lab/`

---

## Step 1 — Clone and configure

```bash
git clone https://github.com/disys-lab/scarlet-composer-studio
cd scarlet-composer-studio/examples/quickstart
cp .env.example .env
```

Edit `.env` — the only required changes:

```bash title=".env (minimum)"
REDIS_HOST=your-redis-host        # or host.docker.internal for local Redis
REDIS_AUTH_TOKEN=your-redis-password
```

!!! note "No Redis? Start one locally"
    ```bash
    docker run -d -p 6379:6379 \
      redis/redis-stack:7.4.0-v1 \
      redis-server --requirepass mypassword
    ```
    Then set `REDIS_HOST=host.docker.internal` in `.env`.

---

## Step 2 — Start the stack

```bash
docker compose up --build -d
```

| Container | Role |
|---|---|
| `scarlet-composer` | Operator UI — Streamlit on **8501**, Tornado on **9099** |
| `hello-agent` | Sample agent — listens on two Messenger buses, echoes messages, heartbeats every 60 s |

Watch progress:
```bash
docker compose logs -f hello-agent
```

---

## Step 3 — Open the Composer UI

Visit **[http://localhost:8501](http://localhost:8501)**

In the sidebar:

1. Enter your **Redis Host** and **Auth Token** → **Save**
2. Click the **Agents** tab — you should see `hello-agent_local` with a green indicator

---

## Step 4 — Send your first message

From a Python REPL on any machine that can reach your Redis:

```python
from scarlets.messaging import Messenger

sender = Messenger("quickstart_headagent", agentId="my-repl")

# hello-agent's agentId is "hello-agent_local"
sender.Send("hello-agent_local", {"task": "ping", "data": "hello world"})

reply = sender.Receive(timeout=5)
print(reply["body"])
# → {"echo": {"task": "ping", "data": "hello world"}, "from": "hello-agent_local", ...}
```

### Check who is online

```python
print(sender.GatherStatus())
# {
#   "hello-agent_local": {
#     "status": "online",
#     "capabilities": ["echo", "heartbeat"],
#     "device_group": "quickstart_subagent",
#     "head_bus": "quickstart_headagent",
#   }
# }
```

### Broadcast to all agents

```python
sender.Broadcast({"directive": "update_config", "version": 2})
```

### Run the smoke test

```bash
python3 smoke_test.py --env .env
```

---

## Step 5 — Explore the local bus

`hello-agent` also listens on `quickstart_subagent` for intra-group communication:

```python
local = Messenger("quickstart_subagent", agentId="peer")
local.Send("hello-agent_local", {"task": "local-ping"})
reply = local.Receive(timeout=5)
print(reply["body"]["channel"])  # "quickstart_subagent"
```

---

## Step 6 — Tear down

```bash
docker compose down
```

---

## Next steps

- [Two-Channel Architecture](concepts/two-channel.md) — understand why `hello-agent` opens two buses
- [Campaign Isolation](concepts/campaigns.md) — run `quickstart` and `training` side-by-side
- [Gustavo Integration](deployment/gustavo.md) — deploy to real edge nodes
- [Extending to your own agent](deployment/docker.md#extending-the-agent-base-image)
