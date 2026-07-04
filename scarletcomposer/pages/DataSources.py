"""
Data Sources page — three-tier data source registration.

Tier 1: data-sources:global               — shared across all nodes/workers
Tier 2: data-sources:worker:{APP_ID}      — specific to one application
Tier 3: data-sources:local:{NODE_ADDRESS} — specific to one physical node

Each entry is a JSON object stored in Redis under the tier key as a hash field
keyed by the data source name.
"""
import streamlit as st
import json, os

from scarlets.utils.ScarletUtils import redisConnect


def _get_client():
    try:
        r = redisConnect(decode_responses=True)
        r.ping()
        return r, None
    except Exception as e:
        return None, str(e)


def _load_tier(r, redis_key):
    try:
        raw = r.hgetall(redis_key)
        result = {}
        for name, val in raw.items():
            try:
                result[name] = json.loads(val)
            except Exception:
                result[name] = {"raw": val}
        return result
    except Exception as e:
        st.error(f"Failed to load {redis_key}: {e}")
        return {}


def _save_entry(r, redis_key, name, entry_dict):
    r.hset(redis_key, name, json.dumps(entry_dict))


def _delete_entry(r, redis_key, name):
    r.hdel(redis_key, name)


def _render_tier(r, title, redis_key, icon):
    with st.expander(f"{icon} {title}  —  `{redis_key}`", expanded=True):
        entries = _load_tier(r, redis_key)

        if entries:
            for name, meta in entries.items():
                col_name, col_type, col_del = st.columns([3, 3, 1])
                with col_name:
                    st.markdown(f"**{name}**")
                with col_type:
                    st.caption(meta.get("type", "—") + "  " + meta.get("description", ""))
                with col_del:
                    if st.button("✕", key=f"del_{redis_key}_{name}"):
                        _delete_entry(r, redis_key, name)
                        st.rerun()
        else:
            st.caption("No data sources registered yet.")

        st.divider()
        st.markdown("**Register a new data source**")

        with st.form(key=f"form_{redis_key}"):
            ds_name = st.text_input("Name", placeholder="e.g. plant_sensor_1")
            ds_type = st.selectbox("Type", ["timeseries", "tabular", "document", "stream", "other"])
            ds_uri = st.text_input("URI / connection string", placeholder="e.g. opc://192.168.1.10:4840")
            ds_desc = st.text_input("Description", placeholder="Optional human-readable note")
            extra_json = st.text_area("Extra metadata (JSON)", value="{}", height=80)
            submitted = st.form_submit_button("Register")

        if submitted:
            if not ds_name:
                st.warning("Name is required.")
            else:
                try:
                    extra = json.loads(extra_json)
                except Exception:
                    extra = {}
                entry = {
                    "name":        ds_name,
                    "type":        ds_type,
                    "uri":         ds_uri,
                    "description": ds_desc,
                    **extra,
                }
                _save_entry(r, redis_key, ds_name, entry)
                st.success(f"Registered '{ds_name}' in {redis_key}")
                st.rerun()


def data_sources_page():
    st.header("Data Sources")
    st.markdown(
        "Register data sources at the appropriate tier. Workers discover sources "
        "by reading global → their own app tier → their local node tier."
    )

    r, err = _get_client()
    if err:
        st.error(f"Cannot connect to Redis: {err}")
        st.info("Configure Redis credentials in the sidebar before using this page.")
        return

    app_id = os.environ.get("APP_ID", "ScarletComposer")
    node_address = os.environ.get("NODE_ADDRESS", os.environ.get("HOSTNAME", "local"))

    _render_tier(r, "Global",      "data-sources:global",               "🌐")
    _render_tier(r, "Worker",      f"data-sources:worker:{app_id}",     "🤖")
    _render_tier(r, "Node-Local",  f"data-sources:local:{node_address}", "🖥️")


data_sources_page()
