"""
Agents page — live status dashboard for all agents registered on a Messenger bus.

Reads from:
  {bus_name}:reg:*  — registry entries written by Messenger.Register()

Shows: agent ID, instance UUID, last heartbeat, status, capabilities, device group.
Auto-refreshes every 15 seconds if the refresh toggle is on.
"""
import streamlit as st
import json, os, time

from scarlets.utils.ScarletUtils import redisConnect


_STALE_THRESHOLD = 90  # seconds without heartbeat → mark stale


def _get_client():
    try:
        r = redisConnect(decode_responses=True)
        r.ping()
        return r, None
    except Exception as e:
        return None, str(e)


def _gather_agents(r, bus_name):
    pattern = f"{bus_name}:reg:*"
    agents = {}
    try:
        for key in r.scan_iter(match=pattern):
            raw = r.get(key)
            if raw:
                try:
                    record = json.loads(raw)
                    agent_id = record.get("agent_id", key.split(":")[-1])
                    agents[agent_id] = record
                except Exception:
                    pass
    except Exception as e:
        st.error(f"Error reading registry: {e}")
    return agents


def _age_label(ts):
    if not ts:
        return "unknown"
    age = time.time() - float(ts)
    if age < 60:
        return f"{int(age)}s ago"
    elif age < 3600:
        return f"{int(age/60)}m ago"
    else:
        return f"{int(age/3600)}h ago"


def _render_agent_card(agent_id, record):
    ts = record.get("ts", 0)
    age = time.time() - float(ts) if ts else 9999
    is_stale = age > _STALE_THRESHOLD

    status_icon = "🔴" if is_stale else ("🟢" if record.get("status") == "online" else "🟡")

    with st.container(border=True):
        c1, c2 = st.columns([5, 2])
        with c1:
            st.markdown(f"#### {status_icon} `{agent_id}`")
            st.caption(
                f"Instance: `{record.get('instance_id', '—')[:12]}…`  ·  "
                f"Bus: `{record.get('scarlet_name', '—')}`  ·  "
                f"Heartbeat: {_age_label(ts)}"
            )
            caps = record.get("capabilities", [])
            if caps:
                st.markdown("**Capabilities:** " + ", ".join(f"`{c}`" for c in caps))
            ds = record.get("data_sources", [])
            if ds:
                st.markdown("**Data sources:** " + ", ".join(f"`{d}`" for d in ds))
        with c2:
            with st.expander("Raw JSON"):
                st.json(record)


def agents_page():
    st.header("Agents")
    st.markdown(
        "Live view of agents registered on a Messenger bus. "
        "An agent is marked stale when its last heartbeat was more than "
        f"{_STALE_THRESHOLD}s ago."
    )

    r, err = _get_client()
    if err:
        st.error(f"Cannot connect to Redis: {err}")
        st.info("Configure Redis credentials in the sidebar before using this page.")
        return

    col_bus, col_refresh = st.columns([4, 1])
    with col_bus:
        bus_name = st.text_input(
            "Bus name",
            value="head-agent",
            help="The scarletName used when constructing the Messenger, e.g. 'head-agent' or your device group.",
        )
    with col_refresh:
        auto_refresh = st.toggle("Auto-refresh", value=False)

    agents = _gather_agents(r, bus_name)

    online = [a for a, rec in agents.items() if (time.time() - float(rec.get("ts", 0))) <= _STALE_THRESHOLD]
    st.markdown(f"**{len(online)} online** / {len(agents)} registered  —  bus `{bus_name}`")

    if not agents:
        st.info("No agents registered on this bus yet.")
    else:
        for agent_id, record in sorted(agents.items()):
            _render_agent_card(agent_id, record)

    if auto_refresh:
        time.sleep(15)
        st.rerun()


agents_page()
