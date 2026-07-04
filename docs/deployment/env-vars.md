# Environment Variables

All configuration is passed via environment variables — no config files required. Set them in `.env`, `docker-compose.yml`, or your container orchestrator.

---

## Required (all deployments)

| Variable | Description | Example |
|---|---|---|
| `REDIS_HOST` | Redis hostname or IP | `redis`, `10.0.1.10` |
| `REDIS_AUTH_TOKEN` | Redis password (AUTH) | `mypassword` |
| `APP_ID` | Campaign identifier — used to derive default bus and group names | `quickstart` |

---

## Optional — Redis

| Variable | Default | Description |
|---|---|---|
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_SSL` | `false` | Set to `true` for TLS connections (e.g., Azure Cache for Redis) |
| `SCARLET_DATA_EXPIRY` | `3600` | TTL in seconds for Mapper / RedisScarlet values |

---

## Optional — Agent Identity and Routing

| Variable | Default | Description |
|---|---|---|
| `NODE_ADDRESS` | Auto-resolved (see [Node Identity](../concepts/identity.md)) | Stable node IP or alias used to form `AGENT_ID = {APP_ID}_{NODE_ADDRESS}` |
| `DEVICE_GROUP` | `{APP_ID}_subagent` | Messenger bus name for the local / intra-group bus |
| `HEAD_BUS` | `{APP_ID}_headagent` | Messenger bus name for the global / coordination bus. Set explicitly for Pattern B (shared head) |

---

## Optional — Composer UI

| Variable | Default | Description |
|---|---|---|
| `STREAMLIT_PORT` | `8501` | Port the Streamlit UI listens on |
| `BACKGROUND_SERVER_PORT` | `9099` | Port for the Tornado identity server |
| `STALE_THRESHOLD` | `120` | Seconds since last heartbeat before an agent is shown as stale in the UI |

---

## Optional — Logging

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Python log level for the agent process (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## Optional — Gustavo / Nebula

| Variable | Default | Description |
|---|---|---|
| `GUSTAVO_MANAGER_URL` | `http://127.0.0.1:8080` | Nebula manager URL. Used by `BackgroundServer._query_nebula_manager` |
| `NEBULA_OVERLAY_NET` | _(unset)_ | Nebula overlay network CIDR — informational, not used by scarlets directly |

---

## .env File Template

```bash
# .env — copy to examples/quickstart/.env and fill in values

# ── Required ─────────────────────────────────────────
REDIS_HOST=your-redis-host
REDIS_AUTH_TOKEN=your-redis-password
APP_ID=quickstart

# ── Redis (optional) ─────────────────────────────────
REDIS_PORT=6379
# REDIS_SSL=true
# SCARLET_DATA_EXPIRY=3600

# ── Agent identity (optional) ────────────────────────
NODE_ADDRESS=local
DEVICE_GROUP=quickstart_subagent
# HEAD_BUS=shared_headagent   # uncomment for Pattern B

# ── Composer UI (optional) ───────────────────────────
# STREAMLIT_PORT=8501
# BACKGROUND_SERVER_PORT=9099
# STALE_THRESHOLD=120

# ── Logging (optional) ───────────────────────────────
# LOG_LEVEL=DEBUG
```

---

## Precedence

1. Variables set in the shell environment override `.env`
2. Variables in `.env` are loaded by Docker Compose or `python-dotenv` if you call `load_dotenv()`
3. Defaults in the code take effect only if the variable is absent from the environment entirely
