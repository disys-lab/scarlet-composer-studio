import streamlit as st
from scarletcomposer.pages.config.loadSidebarCss import force_sidebar_visible
force_sidebar_visible()
import redis
import json
from scarlets.utils.ScarletUtils import redisConnect
from scarletcomposer.pages.config.Sidebar import sidebarInit
sidebarInit()



# Streamlit UI
st.title("Log Viewer")

# Find all hashes in Redis
def get_all_hash_keys(redis_client):
    cursor = b"0"
    matching_keys = []

    # Scan Redis for matching keys
    while cursor != 0:
        cursor, keys = redis_client.scan(cursor=cursor, match=b"logs_*", count=100)
        matching_keys.extend(keys)

    # Decode binary keys to strings
    matching_keys = [key.decode("utf-8") for key in matching_keys]

    return matching_keys

all_hash_keys = None
redis_client=None

try:
    redis_client = redisConnect()
    # Fetch all hashes
    all_hash_keys = get_all_hash_keys(redis_client)

except Exception as e:
    st.error(f"Error connecting to Redis: {e}")


if all_hash_keys:
    selected_hashes = all_hash_keys #st.sidebar.multiselect("Select Hashes to Include", options=all_hash_keys, default=all_hash_keys)

    # Collect unique (app, node) tuples from all selected hashes
    unique_filters = set()
    logs = []

    for hash_name in selected_hashes:
        try:
            app = redis_client.hget(hash_name,"app").decode("utf-8")
            node = redis_client.hget(hash_name, "node").decode("utf-8")
            unique_filters.add((app,node))
            hash_logs = redis_client.hgetall(hash_name)
            logs.append(hash_logs)
        except redis.exceptions.ConnectionError as e:
            st.error(f"Error connecting to Redis: {e}")

    # Create dynamic dropdowns for filtering
    if unique_filters:
        app_options = sorted({app for app, node in unique_filters if app})
        node_options = sorted({node for app, node in unique_filters if node})

        filter_app = st.selectbox("Filter by App ID", ["All"] + app_options)
        filter_node = st.selectbox("Filter by Node IP", ["All"] + node_options)

        # Convert "All" to None for easier filtering logic
        filter_app = None if filter_app == "All" else filter_app
        filter_node = None if filter_node == "All" else filter_node

        # Display filtered logs
        st.subheader("Filtered Logs")
        filtered_logs = []

        for log in logs:
            try:
                if (not filter_app or log.get(b"app",b"").decode("utf-8") == filter_app) or (
                    not filter_node or log.get(b"node",b"").decode("utf-8") == filter_node
                ):
                    decoded ={}
                    for key,value in log.items():
                        decoded[key.decode("utf-8")] = value.decode("utf-8")
                    filtered_logs.append(decoded)
            except json.JSONDecodeError:
                st.warning(f"Invalid log format")

        if filtered_logs:
            st.write(f"Displaying {len(filtered_logs)} log(s):")
            for log in filtered_logs:
                st.json(log)  # Display log as JSON
        else:
            st.info("No logs match the applied filters.")
    else:
        st.info("No valid log data found in the selected hashes.")
else:
    st.warning("No hash keys found in Redis.")
