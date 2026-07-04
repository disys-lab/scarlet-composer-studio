# Scarlet Composer Studio — Quickstart

Stand up a complete Scarlet deployment on a single machine using Docker Compose. This quickstart brings up:

| Container | Role |
|---|---|
| `scarlet-composer` | Operator dashboard — Streamlit UI on port 8501, Tornado identity server on port 9099 |
| `hello-agent` | Sample Scarlet agent — registers on two Messenger buses, echoes messages, broadcasts a heartbeat every 60 s |

The `hello-agent` demonstrates the two-channel architecture:

```
global_bus = Messenger("quickstart_headagent")  # all agents subscribe here
local_bus  = Messenger("quickstart_subagent")   # workers in this group only
```

---

## Prerequisites

- Docker Engine 24+ and Docker Compose v2
- A Redis 6+ instance with AUTH enabled
- Pull access to `ghcr.io/disys-lab/`

---

## 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` — the only required fields:

| Variable | What to set |
|---|---|
| `REDIS_HOST` | Hostname or IP of your Redis instance |
| `REDIS_AUTH_TOKEN` | Redis password |

**Running Redis locally:**
```bash
docker run -d -p 6379:6379 redis/redis-stack:7.4.0-v1 redis-server --requirepass your-password
```
Then set `REDIS_HOST=host.docker.internal` in `.env`.

---

## 2. Start the stack

```bash
docker compose up --build -d
```

Check progress:
```bash
docker compose logs -f hello-agent
docker compose ps
```

---

## 3. Open the Scarlet Composer UI

Visit [http://localhost:8501](http://localhost:8501)

In the sidebar, enter your **Redis Host** and **Auth Token** and click Save. The Agents tab will show `hello-agent_local` once the agent registers.

---

## 4. Send a message to hello-agent

From a Python REPL or script on any machine that has `scarlets` installed and can reach your Redis:

```python
from scarlets.messaging import Messenger

sender = Messenger("quickstart_headagent", agentId="my-repl")

# hello-agent's agentId is APP_ID_NODE_ADDRESS = "hello-agent_local"
sender.Send("hello-agent_local", {"task": "ping", "data": "hello world"})

reply = sender.Receive(timeout=5)
print(reply)
# {"from": "hello-agent_local", "to": "my-repl",
#  "body": {"echo": {"task": "ping", "data": "hello world"}, ...}}
```

### Run the smoke test

```bash
python3 smoke_test.py --env .env
```

### Check registered agents

```python
print(sender.GatherStatus())
```

### Broadcast to all agents

```python
sender.Broadcast({"directive": "update_config", "version": 2})
```

---

## 5. Using the local bus

`hello-agent` also listens on `quickstart_subagent` for intra-group communication:

```python
local = Messenger("quickstart_subagent", agentId="peer-node")
local.Send("hello-agent_local", {"task": "local-ping"})
reply = local.Receive(timeout=5)
# reply["body"]["channel"] == "quickstart_subagent"
```

---

## 6. Tear down

```bash
docker compose down
```

---

## 7. Multi-node deployment

To deploy agents to real edge nodes, see the [Gustavo Integration](../../docs/deployment/gustavo.md) guide. Gustavo pulls and starts agent containers on each worker node; agents are assigned a `NODE_ADDRESS` by the Composer's `getNodeInfo` endpoint and register on the same buses automatically.

---

## 8. Extending to your own agent

1. Copy `hello_agent/` to `my_agent/`
2. Replace `hello_agent.py` with your agent logic — use `Mapper`, `Federator`, or `Messenger` from `scarlets`
3. Update `supervisord.conf` to point at your script
4. Build and push to your registry:
   ```bash
   docker build -t YOUR_REGISTRY:5001/my-agent:latest my_agent/
   docker push YOUR_REGISTRY:5001/my-agent:latest
   ```

See [docs/deployment/docker.md](../../docs/deployment/docker.md) for the full deployment reference.
