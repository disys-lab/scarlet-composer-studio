#!/bin/sh
# gustavo_init.sh — headless bootstrap for the Scarlet quickstart.
#
# Implements the two-channel architecture from DESIGN_v3.md §7 and §12:
#
#   global_bus  → Messenger("quickstart_headagent")  — Pattern A isolated head;
#                                                       workers derive this from APP_ID.
#                                                       Override with HEAD_BUS for Pattern B.
#   local_bus   → Messenger("quickstart_subagent")   — intra-group worker channel
#
# Bootstrap sequence:
#   1. gustavo manager up -s mongo           start MongoDB on the Docker host
#   2. gustavo manager up -s manager         start Nebula manager on the Docker host
#   3. poll gustavo manager check until healthy
#   4. gustavo apps create hello-agent       register the worker app with Nebula
#   5. gustavo device-group create quickstart_headagent  (global coordination group)
#   6. gustavo device-group create quickstart_subagent   (local worker group)
#   7. tail -f /dev/null                     stay alive for CLI access

set -e

# ─── 1. MongoDB ──────────────────────────────────────────────────────────────
echo "[quickstart] Starting MongoDB..."
gustavo manager up -s mongo
echo "[quickstart] Waiting 15 s for MongoDB to initialise..."
sleep 15

# ─── 2. Nebula manager ───────────────────────────────────────────────────────
echo "[quickstart] Starting Nebula manager..."
gustavo manager up -s manager

# ─── 3. Wait for manager health ──────────────────────────────────────────────
echo "[quickstart] Waiting for manager to become healthy..."
until gustavo manager check 2>&1 | grep -q "Manager Up"; do
    echo "[quickstart] Manager not ready, retrying in 5 s..."
    sleep 5
done
echo "[quickstart] Manager is healthy."

# ─── 4. Create quickstart_headagent device group ─────────────────────────────
# This is the global_bus namespace
# Workers open Messenger("quickstart_headagent") as their global_bus when
# HEAD_BUS is unset (Pattern A — isolated campaign).
# The orchestrator / head agent is deployed to this group; in this quickstart
# the orchestrator is the user's REPL / external script, so no agent container
# runs here — but the device group must exist in Nebula for discovery.
echo "[quickstart] Creating quickstart_headagent device group (global coordination channel)..."
gustavo device-group create -n quickstart_headagent

# ─── 6. Create quickstart_subagent device group ──────────────────────────────
# This is the local_bus namespace.  hello-agent registers
# Messenger("quickstart_subagent") as its local channel for intra-group
# peer communication
echo "[quickstart] Creating quickstart_subagent device group (local worker channel)..."
gustavo device-group create -n quickstart_subagent

# ─── 7. Stay alive ───────────────────────────────────────────────────────────
echo "[quickstart] Setup complete."
echo "[quickstart]   global_bus  → Messenger('quickstart_headagent')  registered"
echo "[quickstart]   local_bus   → Messenger('quickstart_subagent')   registered"
echo "[quickstart] Use 'docker exec -it gustavo gustavo --help' for CLI access."
tail -f /dev/null
