"""
Shared pytest fixtures for the Scarlet Composer test suite.

Expected services (start with: docker compose -f docker-compose.test.yml up -d):
  - Redis at localhost:6379  password: testpassword
  - Mock Nebula Manager at localhost:8080

Environment variables override all defaults — run_tests.sh sets them explicitly.
"""
import os, time, socket, threading, asyncio, pytest

# Must be set before any ScarletComposer imports so ScarletBase.__init__ sees them.
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_AUTH_TOKEN", "testpassword")
os.environ.setdefault("APP_ID", "test_worker")
os.environ.setdefault("MANAGER_CONTAINER_HOST", "localhost")
os.environ.setdefault("MANAGER_CONTAINER_PORT", "8080")
os.environ.setdefault("MANAGER_CONTAINER_AUTH_TOKEN", "dGVzdDp0ZXN0")  # "test:test"

from scarlets.utils.ScarletUtils import redisConnect

TORNADO_TEST_PORT = 19099


@pytest.fixture(scope="session")
def redis_client():
    try:
        r = redisConnect()
        r.ping()
        return r
    except Exception as e:
        pytest.skip(f"Redis not available: {e}")


@pytest.fixture(scope="session")
def tornado_server(redis_client):
    """
    Start a BackgroundServer Tornado instance on TORNADO_TEST_PORT.
    Returns the base URL as a string, e.g. 'http://localhost:19099'.
    The server lives for the entire test session.
    """
    from scarletcomposer.pages.config.BackgroundServer import make_app
    import tornado.ioloop

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        app = make_app()
        app.listen(TORNADO_TEST_PORT)
        tornado.ioloop.IOLoop.current().start()

    t = threading.Thread(target=_run, name="TornadoTestThread", daemon=True)
    t.start()

    # Poll until the port accepts connections (up to 5 s).
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            s = socket.create_connection(("localhost", TORNADO_TEST_PORT), timeout=0.2)
            s.close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        pytest.fail(f"Tornado test server did not start on port {TORNADO_TEST_PORT} within 5 s")

    yield f"http://localhost:{TORNADO_TEST_PORT}"
