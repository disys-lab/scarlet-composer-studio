"""
Integration tests for the Redis-backed Scarlet stack.

Requires a running Redis instance. Configure via environment variables:
  REDIS_HOST (default: localhost)
  REDIS_PORT (default: 6379)
  REDIS_AUTH_TOKEN (default: empty string, i.e. no auth)

Run with:
  pytest tests/test_scarlets.py -v
"""
import os, time, json, pytest, numpy as np
from unittest import mock

os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_AUTH_TOKEN", "")
os.environ.setdefault("APP_ID", "test_worker")

from scarlets.core.Mapper import Mapper
from scarlets.utils.ScarletUtils import redisConnect


# ── helpers ──────────────────────────────────────────────────────────────────

def _unique(prefix="test"):
    return f"{prefix}_{int(time.time() * 1000)}"


def _ticking_time(start):
    """
    An unbounded, always-incrementing fake clock for mocking time.time().

    A fixed-length side_effect list isn't safe here: time is a singleton
    module, so patching it patches time.time() for the whole process, not
    just the call site under test - RedisLogger's own internal logging
    (and anything else on the call path) also calls time.time() during the
    same patch window, consuming extra values from a finite list and
    raising StopIteration once it runs dry. Returning a plain function
    instead means it never runs out, however many incidental calls happen
    alongside the ones actually being tested.
    """
    counter = [start]

    def _next():
        counter[0] += 1
        return counter[0]

    return _next


def _cleanup(r, pattern):
    keys = list(r.scan_iter(match=pattern))
    if keys:
        r.delete(*keys)


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def redis_client():
    try:
        r = redisConnect()
        r.ping()
        return r
    except Exception as e:
        pytest.skip(f"Redis not available: {e}")


@pytest.fixture()
def scarlet_name(redis_client):
    name = _unique("scarlet")
    yield name
    _cleanup(redis_client, f"{name}_key-value:*")
    _cleanup(redis_client, f"{name}_key-list")


# ── Mapper tests ──────────────────────────────────────────────────────────────

class TestMapperMap:
    def test_map_scalar(self, scarlet_name):
        m = Mapper(scarlet_name)
        chunks, ok, exc = m.Map(42.0, "scalar_key")
        assert ok, f"Map failed: {exc}"
        assert chunks[0] is True

    def test_map_numpy_array(self, scarlet_name):
        m = Mapper(scarlet_name)
        v = np.ones(100, dtype=np.float32)
        chunks, ok, exc = m.Map(v, "array_key")
        assert ok, f"Map failed: {exc}"

    def test_map_dict(self, scarlet_name):
        m = Mapper(scarlet_name)
        data = {"feature1": [1.0, 2.0], "feature2": [3.0, 4.0]}
        chunks, ok, exc = m.Map(data, "dict_key")
        assert ok, f"Map failed: {exc}"


class TestMapperAllGather:
    def test_allgather_returns_mapped_key(self, scarlet_name):
        m = Mapper(scarlet_name)
        v = np.array([1.0, 2.0, 3.0])
        m.Map(v, "worker_1")

        result, ok, exc = m.AllGather()
        assert ok, f"AllGather failed: {exc}"
        assert "worker_1" in result
        np.testing.assert_array_almost_equal(result["worker_1"], v)

    def test_allgather_multiple_keys(self, scarlet_name):
        m = Mapper(scarlet_name)
        for i in range(3):
            m.Map(np.ones(10) * i, f"worker_{i}")

        result, ok, exc = m.AllGather()
        assert ok
        assert len(result) >= 3
        for i in range(3):
            assert f"worker_{i}" in result

    def test_allgather_empty_scarlet(self, scarlet_name):
        m = Mapper(scarlet_name)
        result, ok, exc = m.AllGather()
        assert ok
        assert isinstance(result, dict)


class TestMapperReduce:
    def test_reduce_sum(self, scarlet_name):
        m = Mapper(scarlet_name)
        v = np.ones(5)
        for i in range(3):
            m.Map(v * (i + 1), f"worker_{i}")

        reduced, ok, exc = m.Reduce(np.zeros(5), op=Mapper.SUM)
        assert ok
        assert np.sum(reduced) > 0

    def test_reduce_max(self, scarlet_name):
        m = Mapper(scarlet_name)
        for i in range(3):
            m.Map(np.ones(5) * (i + 1), f"worker_{i}")

        reduced, ok, exc = m.Reduce(np.zeros(5), op=Mapper.MAX)
        assert ok
        assert np.all(reduced >= 0)


class TestMapperClearAll:
    def test_clearall_empties_scarlet(self, scarlet_name):
        m = Mapper(scarlet_name)
        m.Map(np.ones(10), "worker_0")

        result_before, _, _ = m.AllGather()
        assert len(result_before) >= 1

        m.clearAll()

        result_after, ok, _ = m.AllGather()
        assert ok
        assert len(result_after) == 0


class TestMapperTimeseries:
    def test_multiple_ticks_all_readable(self, scarlet_name):
        m = Mapper(scarlet_name)
        # An always-incrementing fake clock, not real sleep() calls - also
        # avoids the flakiness of two real ticks landing in the same
        # wall-clock second (int(time.time()) has 1s resolution, so two
        # fast successive calls could otherwise collide).
        with mock.patch("scarlets.core.Mapper.time.time", side_effect=_ticking_time(int(time.time()))):
            for i in range(5):
                chunks, ok, exc = m.Map(float(i), "sensorX", timeseries=True)
                assert ok, f"Map failed: {exc}"

        result, ok, exc = m.AllGather()
        assert ok, f"AllGather failed: {exc}"
        assert len(result) == 5
        assert sorted(result.values()) == [0.0, 1.0, 2.0, 3.0, 4.0]

    def test_timeseries_and_plain_keys_coexist(self, scarlet_name):
        m = Mapper(scarlet_name)
        m.Map(42.0, "plain_key")
        with mock.patch("scarlets.core.Mapper.time.time", side_effect=_ticking_time(int(time.time()))):
            for i in range(3):
                m.Map(float(i), "sensorY", timeseries=True)

        result, ok, exc = m.AllGather()
        assert ok, f"AllGather failed: {exc}"
        assert result["plain_key"] == 42.0
        assert len(result) == 4  # 1 plain key + 3 timeseries ticks
        assert m.super.contract.getMapperLength() == 4

    def test_tick_timestamp_ending_in_zero(self, scarlet_name):
        # Specifically exercises the case that silently broke an earlier
        # candidate fix (a Redis glob-pattern approach): a timestamp whose
        # last digit happens to be 0 must not be misclassified as - or
        # collide with - a chunk key's own literal ":0" suffix.
        m = Mapper(scarlet_name)
        ts_ending_in_zero = (int(time.time()) // 10) * 10
        with mock.patch("scarlets.core.Mapper.time.time", return_value=ts_ending_in_zero):
            chunks, ok, exc = m.Map(7.5, "sensorZ", timeseries=True)
        assert ok, f"Map failed: {exc}"

        result, ok, exc = m.AllGather()
        assert ok, f"AllGather failed: {exc}"
        assert len(result) == 1
        assert list(result.values())[0] == 7.5


# ── Messenger tests ───────────────────────────────────────────────────

class TestMessenger:
    def test_register_and_gather(self, redis_client):
        from scarlets.messaging import Messenger

        bus_name = _unique("test_bus")
        try:
            bus = Messenger(bus_name, agentId="agent_a")
            status = bus.GatherStatus()
            assert "agent_a" in status
        finally:
            _cleanup(redis_client, f"{bus_name}:*")

    def test_send_receive(self, redis_client):
        from scarlets.messaging import Messenger

        bus_name = _unique("test_bus")
        try:
            sender   = Messenger(bus_name, agentId="sender")
            receiver = Messenger(bus_name, agentId="receiver")

            sender.Send("receiver", {"hello": "world"})
            msg = receiver.Receive(timeout=2)

            assert msg is not None
            assert msg["body"]["hello"] == "world"
            assert msg["from"] == "sender"
        finally:
            _cleanup(redis_client, f"{bus_name}:*")
            _cleanup(redis_client, "tail_*")
            _cleanup(redis_client, "head_*")

    def test_broadcast(self, redis_client):
        from scarlets.messaging import Messenger

        bus_name = _unique("test_bus")
        try:
            head     = Messenger(bus_name, agentId="head")
            worker_a = Messenger(bus_name, agentId="worker_a")
            worker_b = Messenger(bus_name, agentId="worker_b")

            head.Broadcast({"task": "run"})

            msg_a = worker_a.Receive(timeout=2)
            msg_b = worker_b.Receive(timeout=2)

            assert msg_a is not None
            assert msg_b is not None
        finally:
            _cleanup(redis_client, f"{bus_name}:*")
            _cleanup(redis_client, "tail_*")
            _cleanup(redis_client, "head_*")

    def test_as_tools(self, redis_client):
        from scarlets.messaging import Messenger

        bus_name = _unique("test_bus")
        try:
            bus = Messenger(bus_name, agentId="llm_agent")
            tools = bus.AsTools()
            assert "tools" in tools
            assert "handlers" in tools
            tool_names = [t["name"] for t in tools["tools"]]
            assert "send_message" in tool_names
            assert "gather_status" in tool_names
        finally:
            _cleanup(redis_client, f"{bus_name}:*")
