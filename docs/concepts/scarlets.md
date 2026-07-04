# Scarlet Primitives

A **scarlet** is a named shared-memory object backed by Redis. Multiple agents that share the same `scarletName` participate in the same shared object — no broker, no coordinator. State lives in Redis and the operator controls it.

---

## Class Hierarchy

```
ScarletBase                      ← env vars, Redis config, node identity
└── RedisScarlet                 ← low-level Push / Pull / Clear over Redis
    └── Mapper                   ← Map / AllGather / Reduce / resetAll / clearAll
        └── Federator            ← Aggregate = Reduce + store global

Messenger                        ← Send / Receive / Broadcast / Register / GatherStatus
```

All classes in `ScarletBase` lineage read Redis credentials from environment variables at construction time — no config file required.

---

## Mapper

`Mapper` is the workhorse primitive. Workers write to their own keys independently; any participant reads all values at any time.

```python
from scarlets.core.Mapper import Mapper
import numpy as np

m = Mapper("gradient_bus")

# Workers post their local values (from different processes / machines)
m.Map(np.array([0.1, 0.2, 0.3]), key="worker_osu1")
m.Map(np.array([0.4, 0.5, 0.6]), key="worker_gtech2")

# Any node reads all values
values, ok, _ = m.AllGather()
# {"worker_osu1": array([0.1, 0.2, 0.3]), "worker_gtech2": array([0.4, 0.5, 0.6])}

# Or fold into a single result
total, ok, _ = m.Reduce(np.zeros(3), op=Mapper.SUM)
# array([0.5, 0.7, 0.9])
```

### Key properties

- **Any Python object** can be stored — numpy arrays, dicts, dataclasses, model weights. Values are serialised with `pickle` and compressed with `zlib` before storage.
- **Writes are independent** — workers do not need to coordinate with each other or with the head to post a value.
- **Reads are non-destructive** — `AllGather` does not remove values. They persist until TTL expiry (`SCARLET_DATA_EXPIRY`, default 3600 s) or `clearAll()`.
- **Late joiners work** — a worker that posts its value 10 seconds after the others is automatically included in the next `AllGather` or `Reduce` call.

### Aggregation operations

| Constant | Operation | Use case |
|---|---|---|
| `Mapper.SUM` | `operator.add` | Gradient aggregation, vote counts |
| `Mapper.MUL` | `operator.mul` | Probability products |
| `Mapper.MAX` | `numpy.maximum` | Worst-case anomaly scores |
| `Mapper.MIN` | `numpy.minimum` | Best performance across nodes |

### Timeseries mode

```python
m.Map(sensor_reading, key="sensor_1", timeseries=True)
# stored as "sensor_1:{unix_timestamp}"
```

Multiple time-ordered readings under the same logical key, each with its own TTL.

---

## Federator

`Federator` extends `Mapper` with a pre-wired aggregation pattern for federated learning. It creates two internal Mappers automatically:

- `{scarletName}_mapper_reducer` — collects local contributions from all workers
- `{scarletName}_mapper_global` — stores the aggregated result

```python
from scarlets.formulations.Federator import Federator
from scarlets.types.ScarletBase import ScarletBase
import numpy as np

fdr = Federator("model_sync", op=ScarletBase.SUM)

# Each worker posts its local model update
fdr.Map(local_weights, key="worker_1")
fdr.Map(local_weights, key="worker_2")

# Head agent aggregates and persists the global model
global_weights, ok, _ = fdr.Aggregate(np.zeros_like(local_weights))

# Retrieve the stored global model
result, _, _ = fdr.mpr_global.AllGather()
global_value = result["global"]
```

`Aggregate` is equivalent to `Reduce` followed by `Map("global")` on the global mapper — one call instead of two.

---

## Messenger

`Messenger` provides reliable agent-to-agent communication. Each agent gets a persistent inbox in Redis; messages are sequence-numbered and survive agent restarts.

```python
from scarlets.messaging import Messenger

# On the head agent
head = Messenger("quickstart_headagent", agentId="head_local")
head.Send("worker_osu1", {"task": "run_inference", "model": "anomaly_v2"})

# On the worker
worker = Messenger("quickstart_headagent", agentId="worker_osu1")
msg = worker.Receive(timeout=5)
# {"from": "head_local", "to": "worker_osu1", "seq": 1, "body": {"task": ...}}

# Reply
worker.Send("head_local", {"result": "done", "anomalies": 3})

# Discover all agents on this bus
status = worker.GatherStatus()
```

### Key properties

- **Persistent inboxes** — the read cursor (`head` pointer) lives in Redis. Agents that restart resume from the last unread message.
- **Ordered delivery** — messages are stored with monotonically increasing sequence numbers per recipient.
- **Liveness registry** — every Messenger writes a heartbeat record every 30 s. `GatherStatus()` lets you discover all active agents and their capabilities.
- **Bus-scoped counters** — the same `agentId` can safely receive on multiple buses simultaneously. See [Two-Channel Architecture](two-channel.md).

---

## Scarlet Self-Registration

Every `Mapper` and `Messenger` automatically registers itself in Redis when first instantiated:

```
scarlet_definition_{scarletName}  → JSON definition record
```

This record includes the `scarlet_type`, `description`, `created_by`, and `created_at`. It is written with `overwrite=False` — so the first agent to instantiate a scarlet (typically the head, which also provides the richest description) wins. Workers joining later do not overwrite it.

Pass a meaningful `description` to make the scarlet discoverable by LLM agents:

```python
m = Mapper(
    "gradient_bus",
    description="Accepts numpy float32 arrays of shape (128,). "
                "Key: {APP_ID}_{NODE_ADDRESS}. AllGather returns dict keyed by node address."
)
```

Operators can enrich definitions from source files using `#scarlet` declarations — see [Scarlet Declarations](../guides/declarations.md).
