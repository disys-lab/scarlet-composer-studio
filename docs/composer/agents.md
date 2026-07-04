# Agents Page

The **Agents** tab shows all agents currently registered on the Messenger buses for the configured `APP_ID`.

---

## What It Shows

Each agent that has called `Messenger.ReportStatus(capabilities)` or `Messenger.Register()` appears as a card:

```
┌────────────────────────────────────────┐
│  ● hello-agent_10.42.0.1              │
│                                        │
│  Device group:  quickstart_subagent    │
│  Head bus:      quickstart_headagent   │
│  Last seen:     2 s ago               │
│  Capabilities:  echo  heartbeat        │
└────────────────────────────────────────┘
```

| Field | Source |
|---|---|
| Agent ID | `agentId` passed to `Messenger` |
| Status indicator (green / amber / red) | Time since last heartbeat vs `STALE_THRESHOLD` |
| Device group | `device_group` field in the status dict |
| Head bus | `head_bus` field in the status dict |
| Last seen | `last_seen` field in the liveness registry |
| Capabilities | `capabilities` list in the status dict |

---

## Stale Threshold

An agent is marked **stale** (amber) if its last heartbeat was more than `STALE_THRESHOLD` seconds ago (default: 120 s). It is marked **offline** (red) if no heartbeat has arrived in `2 × STALE_THRESHOLD`.

Messenger writes a heartbeat record to Redis automatically every 30 s from a background thread. You do not need to call `ReportStatus` in a loop — just call it once at startup with your capabilities dict.

```python
global_bus.ReportStatus({
    "status": "online",
    "capabilities": ["echo", "run_inference"],
    "device_group": DEVICE_GROUP,
    "head_bus": HEAD_BUS,
})
```

---

## Sending Messages from the UI

Click the **Send** button on any agent card to open a message dialog. Enter a JSON body and click **Send** — the Composer UI creates a temporary `Messenger` with `agentId="composer_ui"` and calls `Send(target_agent_id, body)`.

This is useful for testing agent responses without writing a Python script.

---

## Filtering

The page filters agents by `APP_ID`. Only agents whose `agentId` starts with `{APP_ID}_` are shown by default. Change `APP_ID` in the sidebar and click **Save** to switch campaigns.

---

## GatherStatus Internals

The page calls `Messenger.GatherStatus()` on startup and on each refresh cycle. This scans all liveness registry keys:

```
{scarletName}:reg:{agentId}  → JSON status blob
```

and returns a dict keyed by `agentId`. The UI renders one card per entry.
