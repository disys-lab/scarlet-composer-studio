import threading, logging, tornado.ioloop, tornado.web
import os, requests, json


def _query_nebula_manager(app_id, manager_host, manager_port, encoded_auth):
    headers = {
        "Authorization": f"Basic {encoded_auth}",
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
    }
    try:
        url = f"http://{manager_host}:{manager_port}/api/v2/apps/{app_id}"
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            return True, response.json()
        return False, {"error": f"status {response.status_code}"}
    except Exception as e:
        return False, {"error": str(e)}


def make_app():

    class IPHandler(tornado.web.RequestHandler):
        """GET /api/v2/getNodeIp — returns the caller's IP address."""
        def get(self):
            x_forwarded_for = self.request.headers.get("X-Forwarded-For")
            if x_forwarded_for:
                client_ip = x_forwarded_for.split(",")[0].strip()
            else:
                client_ip = self.request.remote_ip
            if client_ip == "::1":
                client_ip = "127.0.0.1"
            self.write({"host_ip": client_ip})

    class NodeInfoHandler(tornado.web.RequestHandler):
        """
        GET /api/v2/getNodeInfo?app_id=<APP_ID>

        Returns host_ip, stable node_address (from the Redis node-aliases map),
        and device_group (from Nebula Manager or DEVICE_GROUP env var).

        Agent containers call this at startup when NODE_ADDRESS is not set,
        allowing identity to be resolved without manual configuration.
        """
        def get(self):
            app_id = self.get_argument("app_id", default=None)

            x_forwarded_for = self.request.headers.get("X-Forwarded-For")
            if x_forwarded_for:
                host_ip = x_forwarded_for.split(",")[0].strip()
            else:
                host_ip = self.request.remote_ip
            if host_ip == "::1":
                host_ip = "127.0.0.1"

            redis_host = os.environ.get("REDIS_HOST") or os.environ.get("REDIS_DB_HOST")
            redis_port = os.environ.get("REDIS_PORT") or os.environ.get("REDIS_DB_PORT")
            redis_auth = os.environ.get("REDIS_AUTH_TOKEN") or os.environ.get("REDIS_DB_PWD")
            manager_host = os.environ.get("MANAGER_CONTAINER_HOST")
            manager_port = os.environ.get("MANAGER_CONTAINER_PORT")
            manager_auth = os.environ.get("MANAGER_CONTAINER_AUTH_TOKEN")

            node_address = None
            device_group = None

            # Look up node_address from the node-aliases Redis map
            if redis_host and redis_port and redis_auth:
                try:
                    import redis as redislib
                    r = redislib.StrictRedis(
                        host=redis_host, port=int(redis_port),
                        password=redis_auth, decode_responses=True,
                    )
                    raw = r.get("node-aliases")
                    if raw:
                        alias_data = json.loads(raw)
                        for alias, info in alias_data.items():
                            if info.get("hostname") == host_ip:
                                node_address = alias
                                device_group = info.get("device_group")
                                break
                except Exception as e:
                    logging.warning(f"Could not look up alias from Redis: {e}")

            # Try Nebula Manager for device_group if still unresolved
            if app_id and manager_host and manager_port and manager_auth and not device_group:
                ok, data = _query_nebula_manager(app_id, manager_host, manager_port, manager_auth)
                if ok:
                    device_group = (
                        data.get("device_group")
                        or data.get("env", {}).get("DEVICE_GROUP")
                    )

            self.write({
                "host_ip": host_ip,
                "node_address": node_address or host_ip,
                "device_group": device_group or os.environ.get("DEVICE_GROUP", "default"),
            })

    return tornado.web.Application([
        (r"/api/v2/getNodeIp", IPHandler),
        (r"/api/v2/getNodeInfo", NodeInfoHandler),
    ])


def start_background_tornado(port=9099):
    """Start a Tornado server alongside Streamlit on a secondary port."""
    def _run():
        try:
            app = make_app()
            app.listen(port)
            logging.info(f"Background Tornado running on port {port}")
            tornado.ioloop.IOLoop.current().start()
        except Exception as e:
            logging.error(f"Tornado thread failed: {e}")

    t = threading.Thread(target=_run, name="TornadoThread", daemon=True)
    t.start()
    return t
