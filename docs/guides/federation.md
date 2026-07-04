# Federated Aggregation

`Federator` is the highest-level primitive for federated learning workflows. It wraps `Mapper` with a standard aggregation loop so you don't have to manage the two-mapper pattern yourself.

---

## The Core Loop

```python
# Worker — runs on each edge node
from scarlets.formulations.Federator import Federator
from scarlets.types.ScarletBase import ScarletBase

fdr = Federator("model_sync", op=ScarletBase.SUM)
fdr.Map(local_model_weights, key=NODE_ADDRESS)

# Head — runs once all workers have posted
global_weights, ok, _ = fdr.Aggregate(zero_tensor)
```

That's it. `Aggregate` collects contributions from all workers, reduces them, and writes the result to a global key. The next `Aggregate` call resets the reducer and starts a new round.

---

## Internal Structure

`Federator` creates two `Mapper` instances:

| Internal Mapper | Redis prefix | Purpose |
|---|---|---|
| `mpr_reducer` | `{scarletName}_mapper_reducer_key-value:*` | Per-worker local contributions |
| `mpr_global` | `{scarletName}_mapper_global_key-value:*` | Aggregated global model |

Workers call `fdr.Map(value, key=worker_id)` — this writes to `mpr_reducer`.
The head calls `fdr.Aggregate(init)` — this runs `mpr_reducer.Reduce(init, op)` then `mpr_global.Map(result, key="global")`.

---

## Aggregation Operations

Passed as `op=` at construction time:

| Constant | Redis equivalent | When to use |
|---|---|---|
| `ScarletBase.SUM` | element-wise add | Gradient aggregation (FedAvg) |
| `ScarletBase.MUL` | element-wise multiply | Probabilistic model merging |
| `ScarletBase.MAX` | element-wise max | Worst-case anomaly threshold |
| `ScarletBase.MIN` | element-wise min | Best performance envelope |

---

## Example: FedAvg Gradient Aggregation

```python
import numpy as np
from scarlets.formulations.Federator import Federator
from scarlets.types.ScarletBase import ScarletBase

MODEL_DIM = 128
SCARLET   = "fedavg_round1"

# --- each worker does this ---
worker_id = os.environ["NODE_ADDRESS"]
fdr = Federator(SCARLET, op=ScarletBase.SUM)

local_gradient = compute_local_gradient(local_data)
fdr.Map(local_gradient, key=worker_id)
print(f"[{worker_id}] posted gradient")

# --- head agent does this ---
fdr_head = Federator(SCARLET, op=ScarletBase.SUM)
init     = np.zeros(MODEL_DIM, dtype=np.float32)

# wait until N workers have posted (poll with AllGather)
while True:
    contributions, ok, _ = fdr_head.mpr_reducer.AllGather()
    if len(contributions) >= NUM_WORKERS:
        break
    time.sleep(1.0)

global_gradient, ok, _ = fdr_head.Aggregate(init)
new_global_model = current_global_model - LR * global_gradient
```

---

## Reading the Global Model

After `Aggregate`, the global value lives in `mpr_global` under key `"global"`:

```python
result_dict, ok, _ = fdr_head.mpr_global.AllGather()
global_value = result_dict.get("global")   # numpy array
```

Workers can fetch it for the next round:

```python
result_dict, ok, _ = fdr.mpr_global.AllGather()
global_model = result_dict["global"]
```

---

## Round Management

The reducer is **not automatically cleared** after `Aggregate`. To start a new round, explicitly reset the reducer:

```python
# After Aggregate:
fdr_head.mpr_reducer.resetAll()   # clear all per-worker contributions
```

Or use `clearAll()` to also clear the global result:

```python
fdr_head.mpr_reducer.clearAll()
fdr_head.mpr_global.clearAll()
```

---

## Timeseries Contributions

Workers can post multiple updates over time by appending timestamps:

```python
fdr.Map(gradient, key=f"{worker_id}_{int(time.time())}", timeseries=True)
```

The head's `Aggregate` will sum all timestamped contributions from all keys. Useful for streaming gradient accumulation within a round.

---

## When to Use Mapper vs Federator

| Task | Use |
|---|---|
| Arbitrary read/write — any key, any time | `Mapper` |
| Collect per-worker values and read back dict | `Mapper.AllGather()` |
| Reduce to a single value | `Mapper.Reduce()` |
| Reduce + store global result (FedAvg pattern) | `Federator.Aggregate()` |
| Need both reducer and global namespaces to be explicit | `Federator` (exposes both as `.mpr_reducer` and `.mpr_global`) |
