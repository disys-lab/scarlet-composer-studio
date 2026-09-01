"""
Runs scarletcomposer's existing BackgroundServer (node identity resolution
- getNodeIp/getNodeInfo), unchanged - not a reimplementation, the same
Tornado app, just given its own process via a command override on the
scarlet-composer-app image (see docker-compose.yml's background-server
service) rather than bundled into that image's own supervisord process set.

Port defaults to 9098, not the original 9099: on a real host, whatever
already occupies 9099 is host-specific and outside this service's control
(found empirically on cypress-ai - openwebui's `pipelines` container was
already there) - BACKGROUND_SERVER_PORT exists so a deployment can pick
whatever's actually free, rather than this being silently hardcoded to a
port nothing guarantees is open.

start_background_tornado() only starts a background *thread* and returns
immediately (it was written to run alongside Streamlit's own blocking
server loop in the same process) - this script is that "something else"
now: it starts the thread, then blocks forever so the container sees a
long-running process, same role Streamlit used to play.

Deliberately unauthenticated, matching the original: an agent needs to
resolve its own identity before it has any other config to authenticate
with, so this can't require a composer session token or Gustavo
credential. See scarletcomposer/pages/config/BackgroundServer.py for the
actual handlers.
"""
import os
import threading

from scarletcomposer.pages.config.BackgroundServer import start_background_tornado

if __name__ == "__main__":
    port = int(os.environ.get("BACKGROUND_SERVER_PORT", "9098"))
    start_background_tornado(port=port)
    threading.Event().wait()
