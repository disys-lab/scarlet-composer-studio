# Composer UI — Overview

The Scarlet Composer Studio UI is a Streamlit application that gives operators a real-time view of their distributed agent deployment. It reads directly from Redis — no separate backend API is needed.

---

## Launch

```bash
# From pip installation
scarlet-composer composer gui

# With custom ports
scarlet-composer composer gui --port 8502 --lport 9100

# From Docker
docker run -d -p 8501:8501 -p 9099:9099 \
  -e REDIS_HOST=your-redis-host \
  -e REDIS_AUTH_TOKEN=your-password \
  ghcr.io/disys-lab/scarlet-composer:0.5.0
```

Open **http://localhost:8501** in a browser.

---

## Layout

```
┌──────────────────────────────────────────────────────────────┐
│  Sidebar          │  Main content                            │
│  ─────────────    │  ─────────────────────────────────────   │
│  Redis Host       │  Agents  │  Data Sources  │  Logging     │
│  Auth Token       │                                          │
│  APP_ID           │  (tab content)                           │
│  NODE_ADDRESS     │                                          │
│  [Save]           │                                          │
│                   │                                          │
│  Scarlets page    │                                          │
└──────────────────────────────────────────────────────────────┘
```

---

## Sidebar

The sidebar persists connection settings across tab switches. Changes only take effect after clicking **Save**.

| Field | Description |
|---|---|
| **Redis Host** | Hostname or IP of your Redis instance |
| **Redis Auth Token** | Redis password |
| **APP_ID** | Campaign identifier — filters the agent view |
| **NODE_ADDRESS** | This node's address — used to resolve local identity |

Settings are stored in Streamlit session state. For Docker deployments, pre-populate them via environment variables so the UI opens pre-configured.

---

## Pages

The Composer UI has two top-level pages:

### Main page (`Scarlets.py`)

Three tabs:

| Tab | What it shows |
|---|---|
| **Agents** | Live agent registry, heartbeat status, capability cards |
| **Data Sources** | Three-tier data source registry (global / worker / local) |
| **Logging** | Redis-backed log stream with filtering |

### Scarlets page

Lists all registered scarlet definitions from Redis (`scarlet_definition_*` keys). Allows loading definitions from source files via `#scarlet` declarations and registering them.

---

## BackgroundServer

The Composer UI starts a `BackgroundServer` (Tornado, port 9099) alongside Streamlit. It provides:

- `/api/v2/getNodeInfo` — resolves node hostnames to Nebula overlay IPs via the `node-aliases` Redis key

This is used internally by the Agents tab to display resolved IP addresses instead of raw hostnames.

---

## Automatic Refresh

The UI polls Redis every **5 seconds** by default (Streamlit `st.rerun()` loop). Agent cards update their heartbeat status on each refresh cycle.

Agents that have not sent a heartbeat within `STALE_THRESHOLD` seconds (default 120) appear with a stale indicator.
