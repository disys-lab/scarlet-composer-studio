"""
Shared real-subprocess-worker test infrastructure. Workers run as separate
OS processes (python -m scarlet_agentic_harness) rather than threads sharing
one process, because the harness's LOCAL_NUMBERS env var (and APP_ID/
NODE_ADDRESS generally) are process-global by design - this matches how it
will actually run (separate containers), and avoids inventing thread-local
workarounds for something that's fundamentally multi-process.
"""
import subprocess
import sys
import time

APP_ID = "medtest"
WORKER_DATA = {
    "w1": [5.0, 1.0, 9.0],
    "w2": [3.0, 8.0],
    "w3": [2.0, 7.0, 4.0, 6.0],
}


def spawn_worker(node_address: str, numbers: list[float], env: dict) -> subprocess.Popen:
    worker_env = dict(env)
    worker_env.update({
        "ROLE": "worker",
        "APP_ID": APP_ID,
        "NODE_ADDRESS": node_address,
        "LOCAL_NUMBERS": ",".join(str(n) for n in numbers),
    })
    return subprocess.Popen(
        [sys.executable, "-m", "scarlet_agentic_harness"],
        env=worker_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def wait_for_workers(buses, procs, skill_name: str, expected_count: int, timeout: float = 20) -> set[str]:
    """Poll GatherStatus() until `expected_count` workers report `skill_name`
    as a capability - real capability discovery, not a fixed sleep."""
    deadline = time.time() + timeout
    seen: set[str] = set()
    while time.time() < deadline and len(seen) < expected_count:
        for proc in procs:
            assert proc.poll() is None, f"worker process exited early: {proc.stderr.read()}"
        workers_info = buses.gather_workers()
        seen = {
            agent_id for agent_id, rec in workers_info.items()
            if skill_name in rec.get("capabilities", [])
        }
        time.sleep(0.5)
    assert len(seen) == expected_count, f"only {len(seen)}/{expected_count} workers registered in time: {seen}"
    return seen


def terminate_all(procs) -> None:
    for proc in procs:
        proc.terminate()
    for proc in procs:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
