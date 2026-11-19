"""
Disposable local Redis/Postgres for tests - throwaway `docker run`s, never
a real deployment target. Torn down at the end of the test session
regardless of outcome.
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


_PG_CONTAINER_NAME = "scarlet-harness-test-postgres"
_PG_PORT = 16436
_PG_PASSWORD = "testpass"
_PG_DATABASE = "testdb"


@pytest.fixture(scope="session")
def postgres_conn_info():
    """A real disposable Postgres, seeded with one `sensors` row - used by
    tests exercising local-mode data source queries (query_feature.py)
    against a real connector, not a mock."""
    subprocess.run(["docker", "rm", "-f", _PG_CONTAINER_NAME], capture_output=True)
    subprocess.run(
        [
            "docker", "run", "-d", "--name", _PG_CONTAINER_NAME,
            "-p", f"{_PG_PORT}:5432",
            "-e", f"POSTGRES_PASSWORD={_PG_PASSWORD}",
            "-e", f"POSTGRES_DB={_PG_DATABASE}",
            "postgres:16-alpine",
        ],
        check=True, capture_output=True,
    )
    try:
        for _ in range(60):
            result = subprocess.run(
                ["docker", "exec", _PG_CONTAINER_NAME, "pg_isready", "-U", "postgres"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("test Postgres container did not become ready in time")

        # Retry rather than trusting the probe above.
        #
        # `pg_isready` reports ready a moment before the server will accept
        # a CREATE TABLE, so this seeding step intermittently died with
        # exit 2 and took every dependent test down as a collection error -
        # four of them, on a run that was otherwise green. Measured: it
        # failed on roughly half the runs. The only honest readiness check
        # for "can I run this statement" is running it.
        seed_sql = ("CREATE TABLE sensors (name text, value float8); "
                    "INSERT INTO sensors VALUES ('roll_speed', 1200.5);")
        for attempt in range(30):
            seeded = subprocess.run(
                [
                    "docker", "exec", _PG_CONTAINER_NAME, "psql", "-U", "postgres",
                    "-d", _PG_DATABASE, "-v", "ON_ERROR_STOP=1", "-c", seed_sql,
                ],
                capture_output=True, text=True,
            )
            if seeded.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError(
                f"test Postgres never accepted the seed statement: "
                f"{seeded.stderr.strip()}"
            )

        yield {
            "host": "127.0.0.1", "port": str(_PG_PORT), "database": _PG_DATABASE,
            "user": "postgres", "password": _PG_PASSWORD,
        }
    finally:
        subprocess.run(["docker", "rm", "-f", _PG_CONTAINER_NAME], capture_output=True)
