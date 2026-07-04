"""
QuickStart smoke test — verifies the two-channel send/receive round-trip.

Run after `docker compose up -d` from the quickstart directory:

    python3 smoke_test.py [--env /path/to/.env]

The test:
  1. Loads Redis credentials from .env (or environment).
  2. Registers `smoke-test-repl` on the global bus (quickstart_headagent).
  3. Sends {"task": "ping", "data": "hello world"} to hello-agent_local.
  4. Loops Receive() until the echo reply arrives (up to TIMEOUT seconds),
     skipping heartbeat broadcasts and other non-matching messages.
  5. Repeats steps 2-4 on the local bus (quickstart_subagent).
  6. Reports PASS / FAIL with latency for each channel.
  7. Cleans up its own inbox keys before exiting.
"""

import argparse
import json
import os
import sys
import time

TIMEOUT        = 15          # seconds to wait for each reply
POLL_INTERVAL  = 0.2         # seconds between Receive() calls
GLOBAL_BUS     = "quickstart_headagent"
LOCAL_BUS      = "quickstart_subagent"
HELLO_AGENT_ID = "hello-agent_local"
TEST_AGENT_ID  = "smoke-test-repl"


def load_dotenv(path):
    """Minimal .env loader — does not override already-set env vars."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except FileNotFoundError:
        pass


def redis_connect():
    import redis
    host  = os.environ.get("REDIS_HOST", "localhost")
    port  = int(os.environ.get("REDIS_PORT", 6379))
    token = os.environ.get("REDIS_AUTH_TOKEN", "")
    kwargs = dict(host=host, port=port, decode_responses=False)
    if token:
        kwargs["password"] = token
    return redis.Redis(**kwargs)


def cleanup_inbox(r, bus, agent_id):
    """Delete this agent's inbox keys so next run starts clean."""
    ns = f"{bus}:msg"
    patterns = [
        f"{ns}:tail:{agent_id}",
        f"{ns}:head:{agent_id}",
    ]
    # delete numbered messages
    tail_raw = r.get(f"{ns}:tail:{agent_id}")
    if tail_raw:
        tail = int(tail_raw)
        for i in range(1, tail + 1):
            patterns.append(f"{ns}:{agent_id}:{i}")
    existing = [k for k in patterns if r.exists(k)]
    if existing:
        r.delete(*existing)
    # remove registration
    r.delete(f"{bus}:reg:{agent_id}")


def register_agent(r, bus, agent_id):
    reg_key = f"{bus}:reg:{agent_id}"
    record = {
        "agent_id": agent_id,
        "status":   "online",
        "ts":       time.time(),
        "role":     "test",
    }
    r.set(reg_key, json.dumps(record))


def send_ping(r, bus, target, sender):
    ns   = f"{bus}:msg"
    seq  = r.incr(f"{ns}:tail:{target}")
    key  = f"{ns}:{target}:{seq}"
    payload = {
        "from":        sender,
        "to":          target,
        "seq":         seq,
        "ts":          time.time(),
        "instance_id": "smoke-test",
        "body":        {"task": "ping", "data": "hello world"},
    }
    r.set(key, json.dumps(payload))
    return seq


def receive_echo(r, bus, agent_id, timeout):
    """
    Poll the inbox for a message whose body.echo.task == "ping".
    Skips heartbeat broadcasts and other unrelated messages.
    Returns (msg, latency_seconds) or (None, None) on timeout.
    """
    ns       = f"{bus}:msg"
    head_key = f"{ns}:head:{agent_id}"
    tail_key = f"{ns}:tail:{agent_id}"
    deadline = time.time() + timeout

    while time.time() < deadline:
        head = int(r.get(head_key) or 0)
        tail = int(r.get(tail_key) or 0)

        if head < tail:
            next_seq = head + 1
            msg_key  = f"{ns}:{agent_id}:{next_seq}"

            # Brief retry for the tail-written-before-payload race
            raw = r.get(msg_key)
            if raw is None:
                for _ in range(20):
                    time.sleep(0.01)
                    raw = r.get(msg_key)
                    if raw is not None:
                        break

            # Advance head regardless — don't get stuck on a bad key
            r.set(head_key, next_seq)

            if raw is None:
                continue

            msg  = json.loads(raw)
            body = msg.get("body", {})

            # Skip heartbeats
            if body.get("heartbeat"):
                print(f"  (skipped heartbeat from {msg.get('from')} at seq={next_seq})")
                continue

            # Check for the expected echo
            if body.get("echo", {}).get("task") == "ping":
                latency = time.time() - msg.get("ts", time.time())
                return msg, latency

            # Any other unexpected message — skip and keep waiting
            print(f"  (skipped unexpected message body={body} at seq={next_seq})")
            continue

        time.sleep(POLL_INTERVAL)

    return None, None


def drain_agent_inbox(r, bus, agent_id):
    """Advance the head pointer to the current tail so stale messages are skipped."""
    ns   = f"{bus}:msg"
    tail = r.get(f"{ns}:tail:{agent_id}")
    if tail:
        r.set(f"{ns}:head:{agent_id}", tail)


def run_channel_test(r, bus, label):
    print(f"\n── {label} ({bus}) ──────────────────────────────────────")

    cleanup_inbox(r, bus, TEST_AGENT_ID)
    drain_agent_inbox(r, bus, HELLO_AGENT_ID)   # skip stale messages in hello-agent's inbox
    register_agent(r, bus, TEST_AGENT_ID)
    print(f"  registered {TEST_AGENT_ID} on {bus}")

    t0 = time.time()
    send_ping(r, bus, HELLO_AGENT_ID, TEST_AGENT_ID)
    print(f"  sent ping to {HELLO_AGENT_ID}")

    msg, latency = receive_echo(r, bus, TEST_AGENT_ID, TIMEOUT)

    if msg:
        print(f"  PASS  echo received from {msg.get('from')}  ({latency*1000:.0f} ms round-trip)")
        return True
    else:
        print(f"  FAIL  no echo reply within {TIMEOUT}s")
        return False


def main():
    parser = argparse.ArgumentParser(description="Scarlet QuickStart smoke test")
    parser.add_argument("--env", default=".env", help="Path to .env file")
    args = parser.parse_args()

    load_dotenv(args.env)

    try:
        r = redis_connect()
        r.ping()
        print(f"Connected to Redis at {os.environ.get('REDIS_HOST', 'localhost')}")
    except Exception as e:
        print(f"FAIL  cannot connect to Redis: {e}")
        sys.exit(1)

    results = []
    results.append(run_channel_test(r, GLOBAL_BUS, "Global bus"))
    results.append(run_channel_test(r, LOCAL_BUS,  "Local bus"))

    # Cleanup
    r.delete(f"{GLOBAL_BUS}:reg:{TEST_AGENT_ID}")
    r.delete(f"{LOCAL_BUS}:reg:{TEST_AGENT_ID}")

    print()
    if all(results):
        print("All channels: PASS")
        sys.exit(0)
    else:
        print("Some channels: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
