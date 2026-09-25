# Multi-Node Edge Deployment

This guide walks through deploying Scarlet agents across multiple physical machines using Gustavo and the Nebula overlay network.

---

## Prerequisites

- A Gustavo manager running and accessible on the network
- Redis reachable from all edge nodes
- Docker installed on all nodes
- The `gustavo` CLI on the machine registering apps/device groups - edge nodes themselves don't need it installed (see [Step 4](#step-4-enroll-edge-nodes))

---

## Architecture Overview

```
                     ┌─────────────────────────────────┐
                     │          Gustavo Manager         │
                     │  MongoDB   Nebula CA   API :8080 │
                     └───────────────┬─────────────────┘
                                     │ Nebula overlay (UDP)
           ┌─────────────────────────┼──────────────────────┐
           │                         │                       │
   ┌───────▼───────┐         ┌───────▼───────┐     ┌───────▼───────┐
   │   Node A      │         │   Node B      │     │   Node C      │
   │ hello-agent   │         │ hello-agent   │     │ hello-agent   │
   │ 10.42.0.1     │         │ 10.42.0.2     │     │ 10.42.0.3     │
   └───────────────┘         └───────────────┘     └───────────────┘
           │                         │                       │
           └─────────────── Redis ───┘───────────────────────┘
                   (Mapper data, Messenger queues, node-aliases)
```

---

## Step 1 — Bootstrap the Manager

On the manager machine:

```bash
gustavo manager up mongo      # SERVICE is positional, not a flag
sleep 15
gustavo manager up manager
gustavo manager check 2>&1 | grep "Manager Up"
```

Note the manager's IP address — nodes need it for enrollment.

---

## Step 2 — Register Your App

```bash
cat > /tmp/my_agent_config.yaml << EOF
my-agent:
    docker_image: your-registry.io/my-agent:1.0.0
    env_vars:
        APP_ID: my-campaign
        REDIS_HOST: your-redis-host
        REDIS_PORT: "6379"
        REDIS_AUTH_TOKEN: your-password
        NODE_ADDRESS: ""                  # auto-resolved via Nebula alias
        DEVICE_GROUP: my-campaign_subagent
        MANAGER_HOST: <manager-ip>
        MANAGER_PORT: "8080"
    networks:
        - host
    running: True
    rolling_restart: True
    containers_per:
        server: 1
    privileged: False
    devices: []
EOF

gustavo apps create -n my-agent -f /tmp/my_agent_config.yaml
```

`apps create` only takes `-n`/`-f` - device group membership (and which nodes get this app) is set in Step 3 below, not here.

---

## Step 3 — Create Device Groups

```bash
# Global coordination bus
gustavo device-group create -n my-campaign_headagent -a my-agent

# Local worker bus
gustavo device-group create -n my-campaign_subagent -a my-agent
```

---

## Step 4 — Enroll Edge Nodes

Enrollment is pull-based - it runs **on the edge node itself**, not from the manager targeting a node's IP (there's no `gustavo node` command). On each edge node:

```bash
# Download a worker.env scoped to this device group (auth is your Nebula username/password)
curl -u <username>:<password> \
    http://<manager-ip>:8080/api/device-groups/my-campaign_subagent/worker-env -o worker.env
export GUSTAVO_CONFIG_FILE=worker.env

gustavo worker up
```

If you'd rather not install the `gustavo` CLI on the edge node at all, download `.../worker-compose` (a self-contained `docker-compose.yml`, then `docker compose up -d`) or `.../worker-script` (a launcher you just run) instead - same three options documented in [Gustavo Integration: Node Enrollment](gustavo.md#node-enrollment).

After the worker starts:
- Node registers with the Nebula Manager and receives an overlay IP (e.g., `10.42.0.2`)
- `node-aliases` Redis key is updated: `{"node-B-hostname": "10.42.0.2"}`
- The worker pulls `my-agent` (since it's assigned to `my-campaign_subagent`) and starts the container

---

## Step 5 — Verify All Nodes Are Online

From any machine with Redis access:

```python
from scarlets.messaging import Messenger

head = Messenger("my-campaign_headagent", agentId="ops-console")
status = head.GatherStatus()

for agent_id, info in status.items():
    print(f"{agent_id}: {info.get('status')} — {info.get('device_group')}")
# my-campaign_10.42.0.1: online — my-campaign_subagent
# my-campaign_10.42.0.2: online — my-campaign_subagent
# my-campaign_10.42.0.3: online — my-campaign_subagent
```

Or open the Composer UI and navigate to the **Agents** tab.

---

## Step 6 — Dispatch Work

```python
from scarlets.messaging import Messenger

head = Messenger("my-campaign_headagent", agentId="coordinator")

# Send to a specific node
head.Send("my-campaign_10.42.0.2", {"task": "run_inference", "model": "v3"})

# Broadcast to all workers
head.Broadcast({"directive": "reload_config", "version": 5})
```

---

## Rolling Restarts

To update the agent image across all nodes:

```bash
gustavo apps update -n my-agent -f updated_config.yaml
# With rolling_restart: true, nodes restart one at a time
```

---

## Monitoring

```bash
# Live CPU/memory/disk/container metrics for every enrolled worker
gustavo cache vitals
```

Per-node container logs aren't exposed through the `gustavo` CLI - use `docker logs` directly on the node, or check its containers via `docker ps` (there's no remote log-streaming command).

---

## Adding a Head Agent Container

In production you may want to run the head agent as a container too (rather than from a laptop). Create a separate device group for it, then enroll the coordinator machine *from that machine itself* - enrollment is pull-based, there's no way to push a node into a group from elsewhere:

```bash
gustavo device-group create -n my-campaign_headagent -a my-head-agent
```

```bash
# On the coordinator machine:
curl -u <username>:<password> \
    http://<manager-ip>:8080/api/device-groups/my-campaign_headagent/worker-env -o worker.env
export GUSTAVO_CONFIG_FILE=worker.env
gustavo worker up
```

The head container sets `HEAD_BUS=my-campaign_headagent` and `DEVICE_GROUP=my-campaign_headagent` — it only listens on the global bus and does not join the worker bus.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| Node not appearing in `GatherStatus` | Verify the agent container started: `docker ps` on the node |
| Wrong `agentId` (shows IP `127.0.0.1`) | `NODE_ADDRESS` resolution failed — check `node-aliases` in Redis; ensure the `background-server` service is running (see [Node Identity](../concepts/identity.md)) |
| Agents not receiving messages | Verify `DEVICE_GROUP` matches the Messenger bus name exactly |
| Gustavo manager unreachable | Check firewall; manager listens on UDP (Nebula) and TCP 8080 |
