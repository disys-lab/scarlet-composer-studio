"""
Tests for the three-tier data source model.

Data sources are stored as Redis hashes:
  data-sources:global                — visible to all workers and nodes
  data-sources:worker:{APP_ID}       — scoped to a specific worker type
  data-sources:local:{NODE_ADDRESS}  — scoped to a single node

Each hash field is a source name; the value is a JSON-encoded source record.
"""
import json, time, pytest
from scarlets.utils.ScarletUtils import redisConnect


def _key(tier, qualifier=None):
    return f"data-sources:{tier}:{qualifier}" if qualifier else f"data-sources:{tier}"


@pytest.fixture(autouse=True)
def clean_data_sources(redis_client):
    yield
    patterns = [
        "data-sources:global",
        "data-sources:worker:*",
        "data-sources:local:*",
    ]
    for pattern in patterns:
        keys = list(redis_client.scan_iter(match=pattern))
        if keys:
            redis_client.delete(*keys)


# ── Global tier ───────────────────────────────────────────────────────────────

class TestGlobalDataSources:
    def test_register_and_read(self, redis_client):
        key = _key("global")
        entry = {
            "name": "plant-historian",
            "type": "PI",
            "uri": "pi://10.0.0.50",
            "description": "OSIsoft PI historian",
            "registered_at": time.time(),
        }
        redis_client.hset(key, "plant-historian", json.dumps(entry))
        loaded = json.loads(redis_client.hget(key, "plant-historian"))
        assert loaded["type"] == "PI"
        assert loaded["uri"] == "pi://10.0.0.50"

    def test_list_all(self, redis_client):
        key = _key("global")
        for i in range(3):
            redis_client.hset(key, f"ds_{i}", json.dumps({"name": f"ds_{i}", "type": "REST"}))
        assert len(redis_client.hgetall(key)) == 3

    def test_delete_entry(self, redis_client):
        key = _key("global")
        redis_client.hset(key, "to-delete", json.dumps({"name": "to-delete"}))
        redis_client.hdel(key, "to-delete")
        assert redis_client.hget(key, "to-delete") is None

    def test_update_entry(self, redis_client):
        key = _key("global")
        redis_client.hset(key, "updatable", json.dumps({"uri": "http://v1"}))
        redis_client.hset(key, "updatable", json.dumps({"uri": "http://v2"}))
        loaded = json.loads(redis_client.hget(key, "updatable"))
        assert loaded["uri"] == "http://v2"


# ── Worker tier ───────────────────────────────────────────────────────────────

class TestWorkerDataSources:
    def test_register_scoped_to_app_id(self, redis_client):
        key = _key("worker", "anomaly_detector")
        entry = {"name": "local-model", "type": "file", "uri": "/models/anomaly_v1.pkl"}
        redis_client.hset(key, "local-model", json.dumps(entry))
        loaded = json.loads(redis_client.hget(key, "local-model"))
        assert loaded["uri"] == "/models/anomaly_v1.pkl"

    def test_worker_namespaces_are_isolated(self, redis_client):
        redis_client.hset(_key("worker", "worker_a"), "ds", json.dumps({"name": "ds"}))
        assert redis_client.hget(_key("worker", "worker_b"), "ds") is None

    def test_multiple_workers_independent(self, redis_client):
        for name in ("detector", "forecaster", "classifier"):
            redis_client.hset(_key("worker", name), "model",
                              json.dumps({"uri": f"/models/{name}.pkl"}))
        # Each worker's key exists independently
        for name in ("detector", "forecaster", "classifier"):
            raw = redis_client.hget(_key("worker", name), "model")
            assert json.loads(raw)["uri"] == f"/models/{name}.pkl"


# ── Node-local tier ───────────────────────────────────────────────────────────

class TestLocalDataSources:
    def test_register_node_local(self, redis_client):
        key = _key("local", "osu-node-1")
        entry = {"name": "edge-camera", "type": "RTSP", "uri": "rtsp://10.0.1.5/stream"}
        redis_client.hset(key, "edge-camera", json.dumps(entry))
        loaded = json.loads(redis_client.hget(key, "edge-camera"))
        assert loaded["type"] == "RTSP"

    def test_node_namespaces_are_isolated(self, redis_client):
        redis_client.hset(_key("local", "node-1"), "sensor",
                          json.dumps({"name": "sensor"}))
        assert redis_client.hget(_key("local", "node-2"), "sensor") is None

    def test_extra_json_fields_round_trip(self, redis_client):
        key = _key("local", "edge-node-42")
        entry = {
            "name": "pressure-gauge",
            "type": "Modbus",
            "uri": "modbus://10.0.2.10:502",
            "meta": {"unit": "bar", "range": [0, 100]},
        }
        redis_client.hset(key, "pressure-gauge", json.dumps(entry))
        loaded = json.loads(redis_client.hget(key, "pressure-gauge"))
        assert loaded["meta"]["unit"] == "bar"
        assert loaded["meta"]["range"] == [0, 100]
