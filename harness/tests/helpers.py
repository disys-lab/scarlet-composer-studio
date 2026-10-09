"""
Shared real-subprocess-worker test infrastructure. Workers run as separate
OS processes (python -m scarlet_agentic_harness) rather than threads sharing
one process, because the harness's LOCAL_NUMBERS env var (and APP_ID/
NODE_ADDRESS generally) are process-global by design - this matches how it
will actually run (separate containers), and avoids inventing thread-local
workarounds for something that's fundamentally multi-process.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import pytest
import yaml

from scarlet_agentic_harness import head as head_mod

APP_ID = "medtest"
WORKER_DATA = {
    "w1": [5.0, 1.0, 9.0],
    "w2": [3.0, 8.0],
    "w3": [2.0, 7.0, 4.0, 6.0],
}


_WORKER_HOMES: list[str] = []


def _profiled_home(node_address: str, numbers: list[float]) -> str:
    """
    A throwaway HOME holding one CSV and the config that profiles it.

    `LOCAL_NUMBERS` alone is no longer enough. Every skill now reads its
    data through `local_matrix.choose_source`, which looks for *profiled*
    sources - so a worker given only the env var comes up and answers
    "this worker has no profiled local sources (choose_source returned
    None)". That is what silently disabled this file's tests while nobody
    could run them.

    One column, `value`, holding the numbers the caller asked for, so a
    skill that agrees columns across the fleet agrees on exactly that one.

    Parameters
    ----------
    node_address : str
    numbers : list of float

    Returns
    -------
    str
        Path to use as the worker's HOME.
    """
    home = tempfile.mkdtemp(prefix=f"harness-test-{node_address}-")
    _WORKER_HOMES.append(home)

    csv_path = os.path.join(home, "data.csv")
    with open(csv_path, "w") as fh:
        fh.write("value\n")
        for n in numbers:
            fh.write(f"{n}\n")

    scarlet_dir = os.path.join(home, ".scarlet")
    os.makedirs(scarlet_dir, exist_ok=True)
    with open(os.path.join(scarlet_dir, "config.yaml"), "w") as fh:
        yaml.safe_dump({"sources": [{
            "name": f"{node_address}_local",
            "type": "csv",
            "mode": "local",
            "description": f"{len(numbers)} rows. Columns: value",
            "path": csv_path,
        }]}, fh)
    return home


def spawn_worker(node_address: str, numbers: list[float], env: dict, app_id: str = APP_ID) -> subprocess.Popen:
    worker_env = dict(env)
    worker_env.update({
        "ROLE": "worker",
        "APP_ID": app_id,
        "NODE_ADDRESS": node_address,
        # Kept: the simpler skills still read it (skills/local_data.py).
        "LOCAL_NUMBERS": ",".join(str(n) for n in numbers),
        # Added: everything that goes through local_matrix needs a
        # profiled source, which means a HOME with a .scarlet/config.yaml.
        "HOME": _profiled_home(node_address, numbers),
    })
    proc = subprocess.Popen(
        [sys.executable, "-m", "scarlet_agentic_harness"],
        env=worker_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # When this worker was started, so `wait_for_workers` can tell its
    # registration apart from the identically-named corpse of a previous
    # test. Anything older than this is by definition not this process.
    proc.spawned_at = time.time()
    return proc


def wait_for_workers(buses, procs, skill_name: str, expected_count: int, timeout: float = 20) -> set[str]:
    # No app_id parameter needed here - buses.gather_workers() is already
    # scoped to whichever bus this Buses instance was constructed with
    # (head_config.head_bus), so uniqueness comes from that, not from
    # anything this function does itself.
    """Poll GatherStatus() until `expected_count` workers report `skill_name`
    as a capability - real capability discovery, not a fixed sleep."""
    # Only count registrations newer than this moment.
    #
    # `gather_workers` keeps a record for 60s after its agent dies, and every
    # test in this suite reuses the same agent ids (medtest_w1, ...). So the
    # previous test's corpses satisfy this wait instantly, it returns, and
    # the dispatch goes to processes that no longer exist - surfacing as
    # "no online worker currently reports the 'X' capability", or as a hang.
    # That is the whole of this suite's intermittent failures: median and
    # converse_end_to_end passing on one run and failing on the next
    # depending on how fast the previous test tore down.
    #
    # A live worker heartbeats, so it clears this bar within one beat; a
    # dead one's `ts` is frozen at termination and never will.
    # Taken from the spawn, not from now: a worker can register in the gap
    # between Popen returning and this function being called, and a cutoff
    # taken here would exclude it forever (it only re-reports on a change).
    cutoff = min((getattr(p, "spawned_at", 0.0) for p in procs), default=time.time())
    deadline = time.time() + timeout
    seen: set[str] = set()
    while time.time() < deadline and len(seen) < expected_count:
        for proc in procs:
            assert proc.poll() is None, f"worker process exited early: {proc.stderr.read()}"
        workers_info = buses.gather_workers()
        seen = {
            agent_id for agent_id, rec in workers_info.items()
            if skill_name in rec.get("capabilities", [])
            and rec.get("ts", 0) >= cutoff
        }
        time.sleep(0.5)
    assert len(seen) == expected_count, f"only {len(seen)}/{expected_count} workers registered in time: {seen}"
    return seen


def cleanup_worker_homes() -> None:
    """Remove the throwaway HOMEs `spawn_worker` created."""
    while _WORKER_HOMES:
        shutil.rmtree(_WORKER_HOMES.pop(), ignore_errors=True)


def terminate_all(procs) -> None:
    for proc in procs:
        proc.terminate()
    for proc in procs:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    cleanup_worker_homes()


def run_skill_sync(skill, params, config, buses, timeout: float = 60.0, **kwargs) -> dict:
    """
    head.run_skill() is fire-and-forget by design (see head.py) - it
    delivers its result via a callback, not a return value. Tests want a
    plain synchronous assertion, so this blocks the *calling test thread*
    on a threading.Event until that callback fires. This is legitimate
    local blocking to drive a synchronous caller (a test, same as a REPL),
    not blocking inside run_skill()'s own logic, which is exactly what the
    async rewrite removed.
    """
    done = threading.Event()
    box: dict = {}

    def on_result(result):
        box["result"] = result
        done.set()

    head_mod.run_skill(skill, params, config, buses, on_result, **kwargs)
    assert done.wait(timeout=timeout), "run_skill() callback never fired"
    return box["result"]


def converse_sync(human_message, config, buses, skills, llm_client, timeout: float = 60.0, **kwargs):
    """Same pattern as run_skill_sync(), for head.converse()."""
    done = threading.Event()
    box: dict = {}

    def on_done(result, error):
        box["result"] = result
        box["error"] = error
        done.set()

    head_mod.converse(human_message, config, buses, skills, llm_client, on_done, **kwargs)
    assert done.wait(timeout=timeout), "converse() callback never fired"
    if box["error"] is not None:
        raise box["error"]
    return box["result"]


# Every skill that reads a worker's data now generates worker-local SQL
# with a model, so the multi-process tests cannot run without an endpoint.
# They are skipped rather than deleted: the coverage is real - these are
# the only tests exercising separate OS processes, a live bus, cancellation
# and concurrency - and skipping says "not run here" where a deletion would
# say "not worth running".
#
# Set LLM_BASE_URL (plus LLM_API_KEY / LLM_MODEL) to run them.
requires_llm = pytest.mark.skipif(
    not os.environ.get("LLM_BASE_URL"),
    reason="needs an LLM endpoint: workers generate their own SQL. "
           "Set LLM_BASE_URL, LLM_API_KEY and LLM_MODEL.",
)
