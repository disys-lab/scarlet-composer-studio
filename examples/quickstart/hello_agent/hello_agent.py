"""
hello_agent — minimal Scarlet worker demonstrating the two-channel architecture.

Per DESIGN_v3.md §7, every agent opens exactly two Messenger buses:

    global_bus = Messenger(HEAD_BUS,    agentId=AGENT_ID)
    local_bus  = Messenger(DEVICE_GROUP, agentId=AGENT_ID)

HEAD_BUS resolution (§7.8 / §15.3):
  - If HEAD_BUS is set explicitly → use it as-is.
    Use this for Pattern B (shared head across campaigns):
        HEAD_BUS=common_headagent
  - If HEAD_BUS is not set → derive from APP_ID: f"{APP_ID}_headagent"
    Use this for Pattern A (isolated per-campaign head, the default):
        APP_ID=quickstart  →  global_bus = Messenger("quickstart_headagent")

DEVICE_GROUP is the local_bus name and the Gustavo device group this worker
belongs to (e.g. "quickstart_subagent"). Defaults to f"{APP_ID}_subagent".

Environment variables (injected by Gustavo or docker-compose):
    APP_ID        — Nebula app name / campaign prefix  (default: quickstart)
    NODE_ADDRESS  — stable node alias                  (default: local)
    DEVICE_GROUP  — Gustavo device group / local bus   (default: {APP_ID}_subagent)
    HEAD_BUS      — global bus override for shared-head deployments (optional)
    REDIS_HOST / REDIS_PORT / REDIS_AUTH_TOKEN — Redis connection
"""

import os
import time
import logging
from scarlets.messaging import Messenger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

APP_ID       = os.environ.get("APP_ID", "quickstart")
NODE         = os.environ.get("NODE_ADDRESS", "local")
DEVICE_GROUP = os.environ.get("DEVICE_GROUP", f"{APP_ID}_subagent")
AGENT_ID     = f"{APP_ID}_{NODE}"

# HEAD_BUS: if not set the worker assumes an isolated campaign and derives the
# global bus name from its own APP_ID.  Set it explicitly only when a shared
# head agent manages multiple campaigns (Pattern B, DESIGN_v3.md §7.8).
HEAD_BUS = os.environ.get("HEAD_BUS", f"{APP_ID}_headagent")

# ─── Two-channel setup (DESIGN_v3.md §7) ─────────────────────────────────────
global_bus = Messenger(HEAD_BUS,     agentId=AGENT_ID,
                       description=f"Global coordination channel ({HEAD_BUS})")
local_bus  = Messenger(DEVICE_GROUP, agentId=AGENT_ID,
                       description=f"Intra-group channel ({DEVICE_GROUP})")

# Report capabilities on both channels so both the head agent and peers
# can discover this worker via GatherStatus().
capabilities = {
    "status":       "online",
    "role":         "worker",
    "capabilities": ["echo", "heartbeat"],
    "device_group": DEVICE_GROUP,
    "head_bus":     HEAD_BUS,
    "node_address": NODE,
}
global_bus.ReportStatus(capabilities)
local_bus.ReportStatus(capabilities)

logging.info(
    f"[{AGENT_ID}] registered — "
    f"global_bus='{HEAD_BUS}'  local_bus='{DEVICE_GROUP}'"
)

HEARTBEAT_INTERVAL = 60
last_heartbeat = time.time()


def handle_message(msg, source_bus_name):
    body   = msg.get("body", {})
    sender = msg.get("from", "unknown")
    logging.info(f"[{AGENT_ID}] [{source_bus_name}] received from {sender}: {body}")
    reply_bus = global_bus if source_bus_name == HEAD_BUS else local_bus
    reply_bus.Send(sender, {"echo": body, "from": AGENT_ID, "channel": source_bus_name})
    logging.info(f"[{AGENT_ID}] echoed reply to {sender} on {source_bus_name}")


while True:
    msg = global_bus.Receive(timeout=1)
    if msg:
        handle_message(msg, HEAD_BUS)

    msg = local_bus.Receive(timeout=1)
    if msg:
        handle_message(msg, DEVICE_GROUP)

    now = time.time()
    if now - last_heartbeat >= HEARTBEAT_INTERVAL:
        hb = {"heartbeat": True, "agent": AGENT_ID, "ts": now}
        global_bus.Broadcast(hb)
        local_bus.Broadcast(hb)
        logging.info(f"[{AGENT_ID}] broadcast heartbeat on both channels")
        last_heartbeat = now

    time.sleep(0.05)
