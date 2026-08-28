"""
Disposable local Redis for tests - a throwaway `docker run`, never a real
deployment target. Torn down at the end of the test session regardless of
outcome.
"""
import subprocess
import time

import pytest

_CONTAINER_NAME = "scarlet-harness-test-redis"
_PORT = 16399
_PASSWORD = "testpass"


@pytest.fixture(scope="session")
def redis_conn_info():
    subprocess.run(["docker", "rm", "-f", _CONTAINER_NAME], capture_output=True)
    subprocess.run(
        [
            "docker", "run", "-d", "--name", _CONTAINER_NAME,
            "-p", f"{_PORT}:6379",
            "redis:7-alpine",
            "redis-server", "--requirepass", _PASSWORD,
        ],
        check=True, capture_output=True,
    )
    try:
        for _ in range(60):
            result = subprocess.run(
                ["docker", "exec", _CONTAINER_NAME, "redis-cli", "-a", _PASSWORD, "ping"],
                capture_output=True, text=True,
            )
            if "PONG" in result.stdout:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("test Redis container did not become ready in time")

        yield {"host": "127.0.0.1", "port": str(_PORT), "auth_token": _PASSWORD}
    finally:
        subprocess.run(["docker", "rm", "-f", _CONTAINER_NAME], capture_output=True)
