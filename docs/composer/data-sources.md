# Data Sources Page

The **Data Sources** tab manages a three-tier registry of named data endpoints that agents can discover at runtime. It is backed entirely by Redis — no separate database.

---

## Three Tiers

| Tier | Redis Key | Scope |
|---|---|---|
| **Global** | `data-sources:global` | All campaigns on this Redis instance |
| **Worker** | `data-sources:worker:{APP_ID}` | One campaign — all nodes |
| **Local** | `data-sources:local:{NODE_ADDRESS}` | One node only |

Each tier is a Redis hash. Keys are data source names; values are JSON blobs with connection details.

---

## Adding a Data Source

In the UI:

1. Select the tier from the **Scope** dropdown
2. Enter a **Name** (e.g., `plant_db`, `sensor_feed`)
3. Enter a JSON **Configuration** block
4. Click **Save**

Example configuration:

```json
{
    "type": "postgresql",
    "host": "10.0.1.50",
    "port": 5432,
    "database": "plant_readings",
    "user": "scarlet_reader"
}
```

Alternatively, write directly to Redis:

```python
import redis, json

r = redis.Redis(host=REDIS_HOST, password=REDIS_AUTH_TOKEN, decode_responses=True)

# Global data source
r.hset("data-sources:global", "plant_db", json.dumps({
    "type": "postgresql", "host": "10.0.1.50", "port": 5432
}))

# Worker-scoped (only visible to APP_ID=quickstart)
r.hset("data-sources:worker:quickstart", "local_model", json.dumps({
    "type": "mlflow", "tracking_uri": "http://mlflow.local:5000"
}))

# Node-local (only visible on 10.42.0.2)
r.hset("data-sources:local:10.42.0.2", "raw_sensor", json.dumps({
    "type": "opc-ua", "endpoint": "opc.tcp://192.168.1.10:4840"
}))
```

---

## Reading Data Sources in Agent Code

```python
import redis, json, os

r = redis.Redis(
    host=os.environ["REDIS_HOST"],
    password=os.environ["REDIS_AUTH_TOKEN"],
    decode_responses=True,
)
APP_ID  = os.environ["APP_ID"]
NODE    = os.environ.get("NODE_ADDRESS", "local")

# Merge all three tiers — local overrides worker overrides global
def get_data_sources():
    global_  = r.hgetall("data-sources:global")
    worker_  = r.hgetall(f"data-sources:worker:{APP_ID}")
    local_   = r.hgetall(f"data-sources:local:{NODE}")
    merged   = {**global_, **worker_, **local_}
    return {k: json.loads(v) for k, v in merged.items()}

sources = get_data_sources()
db_config = sources["plant_db"]   # {"type": "postgresql", ...}
```

---

## Use Cases

| Tier | Example |
|---|---|
| Global | Shared PostgreSQL database, MLflow tracking server, S3 bucket |
| Worker | Campaign-specific model registry, feature store for this experiment |
| Local | On-node OPC-UA server, local GPU endpoint, camera stream |

---

## Priority Override

The three-tier merge gives local highest priority. A node can override a global data source with a local one of the same name without affecting other nodes:

```python
# On 10.42.0.2 only — use a local MLflow instance instead of the global one
r.hset("data-sources:local:10.42.0.2", "model_registry", json.dumps({
    "type": "mlflow", "tracking_uri": "http://localhost:5000"
}))
# All other nodes still use data-sources:global → model_registry
```
