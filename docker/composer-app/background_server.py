"""
Runs scarletcomposer's existing BackgroundServer (node identity resolution
- getNodeIp/getNodeInfo) as this container's third supervisord-managed
process, unchanged from what the old Streamlit scarlet-composer image
bundled on port 9099 - not a reimplementation, the same Tornado app.

start_background_tornado() only starts a background *thread* and returns
immediately (it was written to run alongside Streamlit's own blocking
server loop in the same process) - this script is that "something else"
now: it starts the thread, then blocks forever so supervisord sees a
long-running process, same role Streamlit used to play.

Deliberately unauthenticated, matching the original: an agent needs to
resolve its own identity before it has any other config to authenticate
with, so this can't require a composer session token or Gustavo
credential. See scarletcomposer/pages/config/BackgroundServer.py for the
actual handlers.
"""
import threading

from scarletcomposer.pages.config.BackgroundServer import start_background_tornado

if __name__ == "__main__":
    start_background_tornado(port=9099)
    threading.Event().wait()
