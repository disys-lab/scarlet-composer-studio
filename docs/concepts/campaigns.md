# Campaign Isolation

A **campaign** is a self-contained set of agents that share common Messenger buses and Mapper namespaces. Campaign isolation lets you run multiple independent experiments or workflows against the same Redis instance without any cross-talk.

---

## How Isolation Works

Isolation is purely namespace-based. All Redis keys for a campaign are prefixed with the campaign's bus names:

```
{HEAD_BUS}:msg:tail:{agentId}
{HEAD_BUS}:reg:{agentId}
{scarletName}_key-value:{key}
```

Two campaigns with different `APP_ID` values produce non-overlapping key prefixes. No extra configuration is required.

---

## Pattern A — Isolated Campaign

Each campaign manages its own head agent bus. This is the default.

```
APP_ID=quickstart
  global_bus → "quickstart_headagent"
  local_bus  → "quickstart_subagent"

APP_ID=training
  global_bus → "training_headagent"
  local_bus  → "training_subagent"
```

**Setup (default — no extra env vars):**

```python
APP_ID   = os.environ["APP_ID"]   # "quickstart" or "training"
HEAD_BUS = f"{APP_ID}_headagent"  # derived automatically if HEAD_BUS is not set
```

**When to use Pattern A:**
- Independent workloads that must never share a head agent
- Experiments where you want to compare campaigns in isolation
- Any scenario where operational blast radius must be contained per campaign

---

## Pattern B — Shared Head

Multiple campaigns share a single head agent bus. Workers in different campaigns can all be addressed from one place, and the head can route cross-campaign work.

```
HEAD_BUS = "platform_headagent"  (set explicitly on all workers)

APP_ID=campaign_1
  global_bus → "platform_headagent"   ← shared
  local_bus  → "campaign_1_subagent"  ← campaign-private

APP_ID=campaign_2
  global_bus → "platform_headagent"   ← shared
  local_bus  → "campaign_2_subagent"  ← campaign-private
```

**Setup:**

```bash
# In docker-compose.yml or k8s env for all workers
HEAD_BUS=platform_headagent
APP_ID=campaign_1          # still set per worker
DEVICE_GROUP=campaign_1_subagent
```

**When to use Pattern B:**
- A platform-level orchestrator that manages heterogeneous campaigns
- An LLM head agent that needs a single bus to discover all workers regardless of campaign
- Deployments where a single operator needs global visibility without managing N head buses

---

## Running Two Campaigns Side-by-Side

```bash
# Campaign 1 — anomaly detection
docker compose -f docker-compose.yml \
  -e APP_ID=anomaly \
  -e DEVICE_GROUP=anomaly_subagent \
  up -d

# Campaign 2 — federated learning
docker compose -f docker-compose.yml \
  -e APP_ID=fedlearn \
  -e DEVICE_GROUP=fedlearn_subagent \
  up -d
```

Both campaigns run on the same Redis and the same Gustavo manager. Neither can see the other's Messenger queues. Their Mapper namespaces are also separate because scarlet names are typically prefixed with `APP_ID`.

---

## Mapper Namespaces

Campaign isolation for `Mapper` is by convention — prefix the `scarletName` with `APP_ID`:

```python
m = Mapper(f"{APP_ID}_gradient_bus")
# APP_ID=anomaly   → "anomaly_gradient_bus_key-value:..."
# APP_ID=fedlearn  → "fedlearn_gradient_bus_key-value:..."
```

This ensures two campaigns' workers never contaminate each other's aggregation buckets.

---

## Gustavo Device Groups

Gustavo uses device group names as the mechanism for scoping deployments:

```bash
# Quickstart creates these two groups
gustavo device-group create -n quickstart_headagent -a hello-agent
gustavo device-group create -n quickstart_subagent  -a hello-agent
```

Adding a second campaign is:

```bash
gustavo device-group create -n training_headagent -a training-agent
gustavo device-group create -n training_subagent  -a training-agent
```

Nodes are enrolled into the appropriate device group, and Gustavo ensures only matching agent images run on enrolled nodes.

See [Gustavo Integration](../deployment/gustavo.md) for full device group management.
