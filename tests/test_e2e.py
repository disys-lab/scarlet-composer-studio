"""
End-to-end tests for the full agent lifecycle.

Scenario modelled here:
  - Operator uploads node alias YAML → stored at Redis key 'node-aliases'
  - BackgroundServer resolves agent identity when called at startup
  - Worker agent registers on the Messenger bus
  - Head agent dispatches a task via Send / Broadcast
  - Worker receives, processes, and replies
  - Head receives the reply
  - GatherStatus reflects all active agents

Requires both Redis and the mock Nebula Manager (docker-compose.test.yml).
"""
import os, json, time, pytest, requests
from scarlets.utils.ScarletUtils import redisConnect
from scarlets.messaging import Messenger


BUS = "e2e_bus"
CLEARALL_BUS = "e2e_clearall_bus"  # isolated so heartbeats from other tests can't pollute it


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_bus(redis_client):
    yield
    patterns = [f"{BUS}:*", f"{CLEARALL_BUS}:*"]
    keys = []
    for p in patterns:
        keys.extend(redis_client.scan_iter(match=p))
    if keys:
        redis_client.delete(*keys)
    redis_client.delete("node-aliases")
    os.environ.pop("NODE_ADDRESS", None)


# ── Node identity ─────────────────────────────────────────────────────────────

class TestNodeIdentity:
    def test_node_address_env_var_bypasses_all_resolution(self):
        os.environ["NODE_ADDRESS"] = "hardcoded-node-id"
        try:
            from scarlets.types.ScarletBase import ScarletBase
            base = ScarletBase("_test_identity")
            assert base.address == "hardcoded-node-id"
        finally:
            os.environ.pop("NODE_ADDRESS", None)

    def test_tornado_resolves_alias_for_localhost(self, tornado_server, redis_client):
        redis_client.set("node-aliases", json.dumps({
            "e2e-worker-1": {"hostname": "127.0.0.1", "device_group": "e2e-floor"}
        }))
        resp = requests.get(f"{tornado_server}/api/v2/getNodeInfo",
                            params={"app_id": "test_worker"}, timeout=3)
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_address"] == "e2e-worker-1"
        assert data["device_group"] == "e2e-floor"

    def test_tornado_returns_ip_when_no_alias(self, tornado_server, redis_client):
        redis_client.delete("node-aliases")
        resp = requests.get(f"{tornado_server}/api/v2/getNodeInfo", timeout=3)
        data = resp.json()
        # With no alias, node_address == host_ip
        assert data["node_address"] == data["host_ip"]


# ── Agent registration ────────────────────────────────────────────────────────

class TestAgentRegistration:
    def test_single_agent_visible_after_register(self, redis_client):
        bus = Messenger(BUS, agentId="solo_agent")
        status = bus.GatherStatus()
        assert "solo_agent" in status
        rec = status["solo_agent"]
        assert rec["status"] == "online"
        assert rec["scarlet_name"] == BUS

    def test_multiple_agents_all_visible(self, redis_client):
        agents = [Messenger(BUS, agentId=f"agent_{i}") for i in range(4)]
        status = agents[0].GatherStatus()
        for i in range(4):
            assert f"agent_{i}" in status

    def test_report_status_updates_capabilities(self, redis_client):
        bus = Messenger(BUS, agentId="capable_agent")
        bus.ReportStatus({"status": "online", "capabilities": ["anomaly_detection", "forecasting"]})
        status = bus.GatherStatus()
        caps = status["capable_agent"].get("capabilities", [])
        assert "anomaly_detection" in caps
        assert "forecasting" in caps


# ── Task dispatch ─────────────────────────────────────────────────────────────

class TestTaskDispatch:
    def test_head_sends_task_worker_receives(self, redis_client):
        head   = Messenger(BUS, agentId="head_agent")
        worker = Messenger(BUS, agentId="worker_agent")

        head.Send("worker_agent", {"task": "run_inference", "model": "anomaly_v1"})
        msg = worker.Receive(timeout=3)

        assert msg is not None
        assert msg["from"] == "head_agent"
        assert msg["to"] == "worker_agent"
        assert msg["body"]["task"] == "run_inference"

    def test_worker_replies_head_receives(self, redis_client):
        head   = Messenger(BUS, agentId="head_agent")
        worker = Messenger(BUS, agentId="worker_agent")

        head.Send("worker_agent", {"task": "run_inference"})
        task = worker.Receive(timeout=3)
        assert task is not None

        worker.Send("head_agent", {"result": "ok", "anomalies_detected": 0})
        reply = head.Receive(timeout=3)

        assert reply is not None
        assert reply["from"] == "worker_agent"
        assert reply["body"]["result"] == "ok"

    def test_broadcast_reaches_every_worker(self, redis_client):
        head     = Messenger(BUS, agentId="head_agent")
        worker_a = Messenger(BUS, agentId="worker_a")
        worker_b = Messenger(BUS, agentId="worker_b")
        worker_c = Messenger(BUS, agentId="worker_c")

        head.Broadcast({"task": "sync_model", "version": 3})

        for worker, name in [(worker_a, "a"), (worker_b, "b"), (worker_c, "c")]:
            msg = worker.Receive(timeout=3)
            assert msg is not None, f"worker_{name} did not receive broadcast"
            assert msg["body"]["version"] == 3

    def test_messages_are_ordered_per_recipient(self, redis_client):
        sender   = Messenger(BUS, agentId="sender")
        receiver = Messenger(BUS, agentId="receiver")

        for i in range(5):
            sender.Send("receiver", {"seq": i})

        received = [receiver.Receive(timeout=2) for _ in range(5)]
        seqs = [m["body"]["seq"] for m in received if m]
        assert seqs == list(range(5))

    def test_inbox_isolation_between_agents(self, redis_client):
        alice = Messenger(BUS, agentId="alice")
        bob   = Messenger(BUS, agentId="bob")

        alice.Send("bob", {"for": "bob"})

        # Alice's inbox should be empty (nothing sent to alice)
        msg_for_alice = alice.Receive(timeout=1)
        assert msg_for_alice is None

        msg_for_bob = bob.Receive(timeout=2)
        assert msg_for_bob is not None
        assert msg_for_bob["body"]["for"] == "bob"


# ── AsTools / MCP integration ─────────────────────────────────────────────────

class TestAsToolsIntegration:
    def test_skill_structure(self, redis_client):
        bus = Messenger(BUS, agentId="llm_agent")
        skill = bus.AsTools()
        assert "tools" in skill
        assert "handlers" in skill
        tool_names = {t["name"] for t in skill["tools"]}
        assert {"send_message", "check_inbox", "broadcast", "report_status", "gather_status"} == tool_names

    def test_send_via_skill_handler(self, redis_client):
        sender   = Messenger(BUS, agentId="llm_agent")
        receiver = Messenger(BUS, agentId="skill_target")

        skill = sender.AsTools()
        skill["handlers"]["send_message"](
            target_agent_id="skill_target",
            message={"prompt_result": "The answer is 42"},
        )
        msg = receiver.Receive(timeout=3)
        assert msg is not None
        assert msg["body"]["prompt_result"] == "The answer is 42"

    def test_gather_via_skill_handler(self, redis_client):
        bus = Messenger(BUS, agentId="llm_agent")
        skill = bus.AsTools()
        status = skill["handlers"]["gather_status"]()
        assert "llm_agent" in status

    def test_broadcast_via_skill_handler(self, redis_client):
        head    = Messenger(BUS, agentId="llm_head")
        worker  = Messenger(BUS, agentId="llm_worker")

        skill = head.AsTools()
        skill["handlers"]["broadcast"](message={"directive": "pause"})

        msg = worker.Receive(timeout=3)
        assert msg is not None
        assert msg["body"]["directive"] == "pause"


# ── Scarlet self-registration ─────────────────────────────────────────────────

class TestScarletSelfRegistration:
    def setup_method(self, method):
        from scarlets.utils.ScarletUtils import redisConnect
        r = redisConnect(decode_responses=True)
        for key in r.scan_iter("scarlet_definition_*self_reg*"):
            r.delete(key)

    teardown_method = setup_method

    def test_mapper_registers_definition_on_init(self, redis_client):
        import json
        from scarlets.core.Mapper import Mapper
        m = Mapper(
            "self_reg_gradient_bus",
            description="Accepts float32 arrays shape (128,). Key: APP_ID_NODE_ADDRESS.",
        )
        r = redisConnect(decode_responses=True)
        raw = r.get("scarlet_definition_self_reg_gradient_bus")
        assert raw is not None, "Definition not written to Redis"
        defn = json.loads(raw)
        assert defn["scarlet_type"] == "mapper"
        assert defn["scarlet_name"] == "self_reg_gradient_bus"
        assert "float32" in defn["description"]
        assert "created_by" in defn
        assert "created_at" in defn
        m.clearAll()

    def test_messaging_registers_definition_on_init(self, redis_client):
        import json
        bus = Messenger(
            "self_reg_task_bus",
            agentId="test_agent",
            description="Task dispatch bus. Send: {task, model}. Reply: {result, anomalies}.",
        )
        r = redisConnect(decode_responses=True)
        raw = r.get("scarlet_definition_self_reg_task_bus")
        assert raw is not None
        defn = json.loads(raw)
        assert defn["scarlet_type"] == "messaging"
        assert "Task dispatch" in defn["description"]
        bus.clearAll()

    def test_worker_does_not_overwrite_head_definition(self, redis_client):
        import json
        from scarlets.core.Mapper import Mapper
        head = Mapper(
            "self_reg_shared_bus",
            description="Rich head agent description with full schema contract.",
        )
        worker = Mapper("self_reg_shared_bus")  # no description — should not overwrite
        r = redisConnect(decode_responses=True)
        defn = json.loads(r.get("scarlet_definition_self_reg_shared_bus"))
        assert "Rich head agent description" in defn["description"]
        head.clearAll()

    def test_definition_is_json_readable(self, redis_client):
        import json
        from scarlets.core.Mapper import Mapper
        Mapper("self_reg_json_test", description="JSON readable contract.")
        r = redisConnect(decode_responses=True)
        raw = r.get("scarlet_definition_self_reg_json_test")
        defn = json.loads(raw)
        assert isinstance(defn, dict)
        assert all(k in defn for k in (
            "scarlet_type", "scarlet_name", "scarlet_attributes",
            "description", "created_by", "created_at",
        ))


# ── clearAll ──────────────────────────────────────────────────────────────────

class TestClearAll:
    def test_clearall_removes_messages_and_registry(self, redis_client):
        bus = Messenger(CLEARALL_BUS, agentId="cleaner")
        bus.Send("cleaner", {"data": "junk"})

        bus.clearAll()

        assert bus.GatherStatus() == {}
        assert bus.Receive(timeout=1) is None
