"""
Verifies local_config.build_tag_cache()'s own resilience properties
directly, against real services - the function __main__.py calls both
synchronously at worker startup (before this worker ever reports itself
online or answers a dialogue message - see __main__.py's own comment for
why that ordering matters) and on every tick of the periodic refresh
loop thereafter.

Two things intentionally aren't (re-)tested here, with the reasoning
spelled out rather than silently skipped:
  - __main__.py's own startup ordering (build_tag_cache() before the
    first report_status(), before the sleep-first loop starts) is a
    straightforward, directly-readable sequence in that file, not
    complex logic - and the loop's own try/except around a full refresh
    cycle is likewise simple enough to trust from direct inspection. What
    genuinely needed a real test is build_tag_cache()'s own per-source
    isolation, which is real logic with a real failure mode - that's
    what this file covers.
  - Observing tag_cache's actual effect on a dialogue reply's prompt
    would need a real LLM backend (context_fn's content only ever
    leaves a process via an actual model call) - no LLM_BASE_URL is
    configured in this environment, same real gap every other
    real-LLM-dependent test in this suite already has.
"""
import time

from scarlet_agentic_harness import local_config


def test_one_failing_source_does_not_block_others_or_raise(tmp_path, monkeypatch, postgres_conn_info):
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")
    (tmp_path / "config.yaml").write_text(f"""
sources:
  - name: healthy_pg
    type: postgres
    mode: local
    description: "A real, reachable source."
    host: {postgres_conn_info['host']}
    port: {postgres_conn_info['port']}
    database: {postgres_conn_info['database']}
    user: {postgres_conn_info['user']}
    password: {postgres_conn_info['password']}
  - name: unreachable_pg
    type: postgres
    mode: local
    description: "Deliberately broken - wrong port, nothing listening."
    host: 127.0.0.1
    port: 1
    database: testdb
    user: nobody
    password: wrong
  - name: central_erp
    type: mssql
    mode: broker
    description: "Centralized - never attempted at all, not even a failed attempt."
    broker_url: "https://broker.example.com"
""")

    # Must not raise, despite unreachable_pg - this is the actual claim
    # under test: one bad source is caught and skipped, not fatal to the
    # whole pass.
    cache = local_config.build_tag_cache()

    assert "healthy_pg" in cache
    assert cache["healthy_pg"] == [{"table": "public.sensors", "columns": ["name", "value"]}]
    assert "unreachable_pg" not in cache  # failed, silently absent - not a crash, not a wrong answer
    assert "central_erp" not in cache  # mode: broker - never attempted, not a failure at all


def test_a_fresh_call_picks_up_a_live_schema_change(tmp_path, monkeypatch, postgres_conn_info):
    # Proves build_tag_cache() itself does no caching of its own - every
    # call is a fresh introspection. This is exactly the property the
    # periodic refresh loop in __main__.py relies on to pick up a schema
    # change between ticks; synchronous initial population at startup
    # relies on the same fact (the very first call already sees whatever
    # is there at that moment, not some earlier snapshot).
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")
    (tmp_path / "config.yaml").write_text(f"""
sources:
  - name: sensors_pg
    type: postgres
    mode: local
    description: "Test sensor readings."
    host: {postgres_conn_info['host']}
    port: {postgres_conn_info['port']}
    database: {postgres_conn_info['database']}
    user: {postgres_conn_info['user']}
    password: {postgres_conn_info['password']}
""")

    import subprocess
    before = local_config.build_tag_cache()
    assert before["sensors_pg"] == [{"table": "public.sensors", "columns": ["name", "value"]}]

    subprocess.run(
        [
            "docker", "exec", "scarlet-harness-test-postgres", "psql", "-U", "postgres", "-d",
            postgres_conn_info["database"], "-c", "ALTER TABLE sensors ADD COLUMN unit text;",
        ],
        check=True, capture_output=True,
    )

    after = local_config.build_tag_cache()
    assert after["sensors_pg"] == [{"table": "public.sensors", "columns": ["name", "value", "unit"]}]
