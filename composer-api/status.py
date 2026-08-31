"""
Shared agent-status helpers - used by both routers/agents.py and
routers/dashboard.py so "what counts as stale" is defined once, not
duplicated per endpoint the way the old Streamlit pages each redefined
their own magic numbers.
"""
import time

STALE_THRESHOLD_SECONDS = 90  # matches scarletcomposer/pages/Agents.py's own constant


def agent_health(record: dict) -> str:
    """
    "online" / "stale" / "unknown", mirroring Agents.py's status_icon logic
    (🟢 online, 🔴 stale, 🟡 anything else) - kept as the same three-way
    classification so the frontend's StatusPill mapping stays simple.
    """
    ts = record.get("ts", 0)
    age = time.time() - float(ts) if ts else float("inf")
    if age > STALE_THRESHOLD_SECONDS:
        return "stale"
    if record.get("status") == "online":
        return "online"
    return "unknown"
