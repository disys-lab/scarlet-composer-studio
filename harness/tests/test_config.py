"""
Unit tests for HarnessConfig.from_env()'s NODE_ADDRESS resolution chain -
no Redis, no subprocess, no real network calls (requests.get/socket are
monkeypatched). Mirrors scarlets.types.ScarletBase._resolveNodeAddress()'s
own priority order: env var -> Gustavo manager's getNodeInfo -> local
hostname IP -> "127.0.0.1".

Every test explicitly delenv's NODE_ADDRESS/DEVICE_GROUP *before* acting,
even ones that then set them - _resolve_node_address() sets these directly
via os.environ (not through monkeypatch), mirroring ScarletBase's own real
side-effecting behavior (see config.py's docstring for why). Registering
the delenv first is what makes monkeypatch's teardown clean up that direct
write too, since it restores each key to whatever state existed at the
first setenv/delenv call for that key - not just what monkeypatch itself
last wrote.
"""
import os

import pytest

from scarlet_agentic_harness.config import HarnessConfig


REQUIRED_ENV = {
    "ROLE": "worker",
    "APP_ID": "cfgtest",
    "REDIS_HOST": "unused",
    "REDIS_PORT": "6379",
    "REDIS_AUTH_TOKEN": "unused",
}


def _set_required(monkeypatch):
    monkeypatch.delenv("NODE_ADDRESS", raising=False)
    monkeypatch.delenv("DEVICE_GROUP", raising=False)
    monkeypatch.delenv("MANAGER_HOST", raising=False)
    monkeypatch.delenv("MANAGER_PORT", raising=False)
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)


def test_explicit_node_address_wins_no_resolution_attempted(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("NODE_ADDRESS", "10.0.0.5")

    def _fail_if_called(*a, **k):
        raise AssertionError("requests.get should never be called - NODE_ADDRESS was set explicitly")

    monkeypatch.setattr("requests.get", _fail_if_called)

    config = HarnessConfig.from_env()
    assert config.node_address == "10.0.0.5"


def test_getnodeinfo_resolves_when_manager_configured(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("MANAGER_HOST", "manager.internal")
    monkeypatch.setenv("MANAGER_PORT", "8080")

    calls = []

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {"node_address": "10.0.1.42", "device_group": "resolved_subagent"}

    def _fake_get(url, params=None, timeout=None):
        calls.append((url, params))
        return _FakeResponse()

    monkeypatch.setattr("requests.get", _fake_get)

    config = HarnessConfig.from_env()

    assert config.node_address == "10.0.1.42"
    assert config.device_group == "resolved_subagent"
    assert calls == [("http://manager.internal:8080/api/v2/getNodeInfo", {"app_id": "cfgtest"})]
    # Side effect, mirroring ScarletBase - later scarlets primitives
    # constructed in this process see the resolved value directly.
    assert os.environ["NODE_ADDRESS"] == "10.0.1.42"


def test_explicit_device_group_wins_over_getnodeinfo_response(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("MANAGER_HOST", "manager.internal")
    monkeypatch.setenv("MANAGER_PORT", "8080")
    monkeypatch.setenv("DEVICE_GROUP", "explicit_subagent")

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {"node_address": "10.0.1.42", "device_group": "resolved_subagent"}

    monkeypatch.setattr("requests.get", lambda *a, **k: _FakeResponse())

    config = HarnessConfig.from_env()
    assert config.device_group == "explicit_subagent"


def test_getnodeinfo_failure_falls_back_to_hostname(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("MANAGER_HOST", "manager.internal")
    monkeypatch.setenv("MANAGER_PORT", "8080")

    def _raise(*a, **k):
        raise ConnectionError("manager unreachable")

    monkeypatch.setattr("requests.get", _raise)
    monkeypatch.setattr("socket.gethostbyname", lambda host: "192.168.1.7")

    config = HarnessConfig.from_env()
    assert config.node_address == "192.168.1.7"


def test_no_manager_configured_skips_http_goes_straight_to_hostname(monkeypatch):
    _set_required(monkeypatch)  # MANAGER_HOST/PORT deliberately left unset

    def _fail_if_called(*a, **k):
        raise AssertionError("requests.get should never be called - no manager configured")

    monkeypatch.setattr("requests.get", _fail_if_called)
    monkeypatch.setattr("socket.gethostbyname", lambda host: "192.168.1.9")

    config = HarnessConfig.from_env()
    assert config.node_address == "192.168.1.9"


def test_hostname_resolution_failure_falls_back_to_loopback(monkeypatch):
    _set_required(monkeypatch)  # no manager configured

    def _raise(host):
        raise OSError("no network")

    monkeypatch.setattr("socket.gethostbyname", _raise)

    config = HarnessConfig.from_env()
    assert config.node_address == "127.0.0.1"


def test_empty_string_env_vars_treated_as_unset(monkeypatch):
    """scarlet-agent-base's own Dockerfile (and this harness's own,
    extending it) declare several optional vars as ENV KEY="" placeholders
    rather than leaving them genuinely unset - found via a real `docker
    run` against the actual built image, where DEVICE_GROUP came back ""
    instead of the intended f"{app_id}_subagent" fallback. Reproduces that
    exact shape here: explicitly present, empty-string values, not merely
    absent ones (monkeypatch.delenv wouldn't catch this class of bug -
    that's "absent", not "present but empty")."""
    _set_required(monkeypatch)
    monkeypatch.setenv("DEVICE_GROUP", "")
    monkeypatch.setenv("HEAD_BUS", "")
    monkeypatch.setenv("MANAGER_HOST", "")  # also base-image's own default
    monkeypatch.setattr("requests.get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("requests.get should never be called - MANAGER_HOST is empty")
    ))
    monkeypatch.setattr("socket.gethostbyname", lambda host: "10.9.9.9")

    config = HarnessConfig.from_env()
    assert config.device_group == "cfgtest_subagent"
    assert config.head_bus == "cfgtest_headagent"


def test_getnodeinfo_non_200_falls_back_to_hostname(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("MANAGER_HOST", "manager.internal")
    monkeypatch.setenv("MANAGER_PORT", "8080")

    class _FakeResponse:
        status_code = 404

        def json(self):
            raise AssertionError("must not be called on a non-200 response")

    monkeypatch.setattr("requests.get", lambda *a, **k: _FakeResponse())
    monkeypatch.setattr("socket.gethostbyname", lambda host: "192.168.1.11")

    config = HarnessConfig.from_env()
    assert config.node_address == "192.168.1.11"
