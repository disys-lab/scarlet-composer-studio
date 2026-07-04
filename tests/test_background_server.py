"""
Tests for the BackgroundServer Tornado endpoints.

  GET /api/v2/getNodeIp    — returns the caller's IP
  GET /api/v2/getNodeInfo  — resolves node_address from Redis node-aliases;
                             falls back to mock Nebula Manager for device_group
"""
import json, pytest, requests


# ── helpers ───────────────────────────────────────────────────────────────────

def _set_aliases(redis_client, aliases):
    redis_client.set("node-aliases", json.dumps(aliases))


def _clear_aliases(redis_client):
    redis_client.delete("node-aliases")


# ── /api/v2/getNodeIp ─────────────────────────────────────────────────────────

class TestGetNodeIp:
    def test_returns_host_ip_field(self, tornado_server):
        resp = requests.get(f"{tornado_server}/api/v2/getNodeIp", timeout=3)
        assert resp.status_code == 200
        data = resp.json()
        assert "host_ip" in data
        assert data["host_ip"]  # non-empty

    def test_localhost_normalised(self, tornado_server):
        resp = requests.get(f"{tornado_server}/api/v2/getNodeIp", timeout=3)
        ip = resp.json()["host_ip"]
        # ::1 should be normalised to 127.0.0.1
        assert ip != "::1"


# ── /api/v2/getNodeInfo ───────────────────────────────────────────────────────

class TestGetNodeInfo:
    def setup_method(self, method):
        from scarlets.utils.ScarletUtils import redisConnect
        _clear_aliases(redisConnect())

    def teardown_method(self, method):
        from scarlets.utils.ScarletUtils import redisConnect
        _clear_aliases(redisConnect())

    def test_response_shape(self, tornado_server):
        resp = requests.get(f"{tornado_server}/api/v2/getNodeInfo",
                            params={"app_id": "test_worker"}, timeout=3)
        assert resp.status_code == 200
        data = resp.json()
        assert "host_ip" in data
        assert "node_address" in data
        assert "device_group" in data

    def test_without_aliases_node_address_is_ip(self, tornado_server, redis_client):
        _clear_aliases(redis_client)
        resp = requests.get(f"{tornado_server}/api/v2/getNodeInfo",
                            params={"app_id": "test_worker"}, timeout=3)
        data = resp.json()
        assert data["node_address"] == data["host_ip"]

    def test_alias_resolved_from_redis(self, tornado_server, redis_client):
        _set_aliases(redis_client, {
            "prod-node-1": {"hostname": "127.0.0.1", "device_group": "factory-floor"}
        })
        resp = requests.get(f"{tornado_server}/api/v2/getNodeInfo",
                            params={"app_id": "test_worker"}, timeout=3)
        data = resp.json()
        assert data["node_address"] == "prod-node-1"
        assert data["device_group"] == "factory-floor"

    def test_device_group_from_mock_manager_when_no_aliases(self, tornado_server, redis_client):
        _clear_aliases(redis_client)
        resp = requests.get(f"{tornado_server}/api/v2/getNodeInfo",
                            params={"app_id": "test_worker"}, timeout=3)
        data = resp.json()
        # Mock manager returns "test-floor"; env fallback is "default"
        assert data["device_group"] in ("test-floor", "default")

    def test_multiple_aliases_matches_correct_one(self, tornado_server, redis_client):
        _set_aliases(redis_client, {
            "node-alpha": {"hostname": "10.0.0.1",   "device_group": "floor-a"},
            "node-beta":  {"hostname": "10.0.0.2",   "device_group": "floor-b"},
            "node-local": {"hostname": "127.0.0.1",  "device_group": "local-floor"},
        })
        resp = requests.get(f"{tornado_server}/api/v2/getNodeInfo",
                            params={"app_id": "test_worker"}, timeout=3)
        data = resp.json()
        # localhost → should match node-local
        assert data["node_address"] == "node-local"
        assert data["device_group"] == "local-floor"

    def test_no_app_id_still_returns_valid_response(self, tornado_server):
        resp = requests.get(f"{tornado_server}/api/v2/getNodeInfo", timeout=3)
        assert resp.status_code == 200
        data = resp.json()
        assert "node_address" in data
