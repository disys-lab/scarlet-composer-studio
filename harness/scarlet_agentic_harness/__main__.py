"""
Entrypoint: python -m scarlet_agentic_harness

Role branch, same image either way (ROLE=head or ROLE=worker env var) -
see README for why. Not deployed anywhere yet; this is for local/manual runs
against a real Redis while building.
"""
import json
import sys
import threading
import time

from scarlets.utils.RedisLogger import RedisLogger

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.cancellation import CancellationRegistry, describe_in_flight
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness import data_profile
from scarlet_agentic_harness.dialogue import AgentDialogue
from scarlet_agentic_harness.llm.client import LLMClient
from scarlet_agentic_harness import local_config
from scarlet_agentic_harness import observability
from scarlet_agentic_harness.skills.registry import discover_skills
from scarlet_agentic_harness import head as head_mod
from scarlet_agentic_harness import reasoning
from scarlet_agentic_harness import worker as worker_mod


def main() -> None:
    """
    Entrypoint for ``python -m scarlet_agentic_harness``.

    Branches on `HarnessConfig.role` (same image either way):

    - ``worker``: reports status/capabilities, starts a periodic
      local-data-source tag-cache refresh, wires up `AgentDialogue` (if
      an LLM backend is configured), and starts dispatch via
      `worker.start_dispatch`. Blocks forever afterward - dispatch runs
      entirely on the bus router's own threads.
    - ``head``: reports status, then either a manual-dispatch stdin REPL
      (JSON lines of ``{"skill": ..., "params": ...}``, if no LLM
      backend is configured) or an LLM-backed chat REPL (one message per
      stdin line, via `head.converse`) - logging every `converse` event
      to stderr as JSON in the latter case.

    Reads all configuration from the environment via `HarnessConfig.from_env`.
    """
    config = HarnessConfig.from_env()
    buses = Buses(config)
    skills = discover_skills()

    if config.role == "worker":
        # Built synchronously, before this worker ever reports itself
        # online or answers a dialogue message - a boot or a post-crash
        # reboot must not leave tag grounding empty for a whole refresh
        # interval (default 300s) just because the periodic loop below
        # hasn't ticked yet. Per-source failures are already caught inside
        # build_tag_cache() itself - one bad source never blocks this.
        tag_cache: dict[str, list] = local_config.build_tag_cache()

        # Built in the same synchronous pre-announcement window as the tag
        # cache, and for the same reason: a peer that reads this worker's
        # record the instant it comes online must not see an empty profile.
        #
        # Where tag_cache answers "which columns exist", this answers "how
        # much data is there and what shape is it" - the row count and the
        # numeric column count. That pair is what the consensus step
        # negotiates over, so it is published as structured numbers rather
        # than left to be inferred from prose later. Profiling is one-shot
        # by design (the sprint objective says a worker builds its
        # understanding once at boot); the refresh loop below deliberately
        # does NOT rebuild it, so a mid-run config edit changes tags but
        # not shapes.
        #
        # Per-source failures are swallowed inside profile_sources()
        # itself, same contract as build_tag_cache() - one unreadable
        # source must never stop a worker booting.
        data_profiles: dict = data_profile.profile_sources()

        # The readable companion to those numbers, written where the
        # worker's own LLM can be pointed at it later. Best-effort: an
        # unwritable home is not a reason to refuse to boot, since the
        # structured profiles above are the authoritative copy and they
        # live in memory regardless.
        data_profile.write_profile_markdown(data_profiles)

        # activity_mapper rides along in the status record so a reader
        # never has to know (or be told) this name out of band: it gathers
        # agents from the one bus it already has, and each agent's record
        # says where its activity lives. That keeps working when a fleet
        # is split across Gustavo apps and the names differ per app - see
        # config.activity_mapper's own comment. Must be passed at BOTH
        # report_status call sites (here and in the refresh loop below):
        # report_status builds the record from scratch each call, so a
        # re-report without it would silently overwrite the field away.
        buses.report_status(
            capabilities=list(skills.keys()),
            extra={
                "activity_mapper": config.activity_mapper,
                # Published as structured numbers so a peer can read this
                # worker's dimensions straight off the status record,
                # without a dialogue round trip and without inferring
                # "(80, 5)" out of English. The consensus step reasons over
                # these; the prose profile is only for a model to read.
                "data_shapes": {n: p["shape"] for n, p in data_profiles.items()},
            },
        )

        # report_status() above (and the tag cache build before it) only
        # ever run once, at startup - data_sources/tags would otherwise
        # never reflect a site engineer hand-editing ~/.scarlet/config.yaml
        # (or a source's schema actually changing) after this process
        # started, short of a restart. capabilities don't change at
        # runtime (skills are still static/bundled-in-the-image), so
        # re-running this is purely about picking up local config/schema
        # changes.
        #
        # The whole body is wrapped so one bad cycle - report_status()
        # itself hitting a transient Redis error, say, not just a single
        # source's list_tags() failing (already handled inside
        # build_tag_cache()) - logs and moves on to the next cycle instead
        # of killing this thread and silently ending every future refresh,
        # tags and the data_sources report alike, for the rest of this
        # process's life.
        def _refresh_data_sources_loop():
            nonlocal tag_cache
            while True:
                time.sleep(config.data_source_refresh_interval)
                try:
                    tag_cache = local_config.build_tag_cache()
                    # Shapes are published from data_profiles, so if the
                    # config changed under us this is what stops the status
                    # record advertising dimensions the worker no longer has.
                    # In-place, so every HarnessContext already holding this
                    # dict sees the new values too.
                    data_profile.refresh_if_stale(data_profiles)
                    # extra= must match the startup call above - see its
                    # comment: report_status rebuilds the record each
                    # time, so omitting it here would drop activity_mapper
                    # from the record on the first refresh.
                    buses.report_status(
                        capabilities=list(skills.keys()),
                        extra={
                            "activity_mapper": config.activity_mapper,
                            # Must be repeated here for the same reason
                            # activity_mapper is: report_status rebuilds the
                            # record from scratch, so omitting it would drop
                            # every worker's shape on the first refresh tick
                            # and silently break consensus 300s into a run.
                            # data_profiles is NOT rebuilt - profiling is
                            # one-shot at boot by design - so this re-reports
                            # the same boot-time numbers.
                            "data_shapes": {n: p["shape"] for n, p in data_profiles.items()},
                        },
                    )
                except Exception as exc:
                    RedisLogger.warning(f"[{config.agent_id}] data source refresh cycle failed: {exc}")

        threading.Thread(target=_refresh_data_sources_loop, daemon=True).start()

        # Activity publishing (observability.py) is unconditional - it's
        # useful for a dashboard/human regardless of whether this worker
        # has LLM access. AgentDialogue is only constructed if an LLM
        # backend is configured - without one, agent_message traffic is
        # simply dropped (see worker.start_dispatch), same as any other
        # message nobody's set up to handle. Its context_fn now has real
        # grounding data to draw on: the registry's own in-flight
        # request_ids, not a placeholder.
        registry = CancellationRegistry(
            activity_mapper=observability.activity_mapper(config.activity_mapper),
            agent_id=config.agent_id,
        )
        # One LLMClient, reused for both agent_message conversations
        # (dialogue) and ctx.mint_scarlet() (see worker.start_dispatch) -
        # same backend either way, no reason to construct two.
        worker_llm_client = LLMClient(config) if config.llm_base_url else None
        dialogue = (
            AgentDialogue(
                buses.global_bus, worker_llm_client,
                context_fn=lambda: {
                    "in_flight_status": describe_in_flight(registry.snapshot()),
                    # Grounds a reply like "does anyone have roll_speed for
                    # equipment 1234" in this worker's own real local
                    # sources - redacted (name/type/mode/description only,
                    # see local_config.describe_sources()) plus each
                    # source's real, live tags/columns from tag_cache
                    # (Option 4+2: computed ahead of time on the periodic
                    # refresh above, not looked up live per reply - see
                    # that loop's own comment for why). describe_sources()
                    # itself still re-reads the config file fresh on every
                    # call; only the tags are cached.
                    "local_data_sources": local_config.describe_sources(tag_cache=tag_cache),
                },
            )
            if worker_llm_client else None
        )
        worker_mod.start_dispatch(
            config, buses, skills, dialogue=dialogue, registry=registry,
            llm_client=worker_llm_client, data_profiles=data_profiles,
        )
        print(
            f"[{config.agent_id}] worker online, skills={list(skills.keys())}, "
            f"dialogue={'on' if dialogue else 'off'}",
            file=sys.stderr,
        )
        # Dispatch now happens entirely through buses.global_router's own
        # background thread plus one handler thread per in-flight request
        # (see worker.start_dispatch) - nothing left for the main thread to
        # do but stay alive.
        threading.Event().wait()
    else:
        buses.report_status(capabilities=[])
        print(f"[{config.agent_id}] head online.", file=sys.stderr)
        if not config.llm_base_url:
            print(
                "No LLM_BASE_URL configured yet - the LLM tool-loop is not "
                "wired up (see README: pending real credentials). "
                "Manual dispatch mode: pipe JSON lines of the form "
                '{"skill": "median", "params": {}} on stdin.',
                file=sys.stderr,
            )
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    req = json.loads(line)
                    skill = skills[req["skill"]]
                    # run_skill() is fire-and-forget (delivers its result via
                    # on_result, not a return value - see head.py). This is a
                    # one-line-at-a-time REPL, so blocking *this* loop on an
                    # Event until that one call's result arrives is a
                    # legitimate, local use of blocking - it drives a
                    # synchronous CLI, it isn't blocking inside run_skill()'s
                    # own logic.
                    done = threading.Event()
                    box: dict = {}

                    def on_result(result):
                        box["result"] = result
                        done.set()

                    head_mod.run_skill(skill, req.get("params", {}), config, buses, on_result)
                    done.wait()
                    print(json.dumps(box["result"]))
                except Exception as exc:  # surfaced to the operator driving stdin manually
                    print(json.dumps({"status": "error", "detail": str(exc)}))
        else:
            # head.converse() itself is tested (tests/test_head_converse.py,
            # tests/test_converse_end_to_end.py) with a scripted fake LLM
            # client - this specific wiring (a real LLMClient against a real
            # backend, driven from stdin) is not yet verified against a live
            # endpoint, since no credentials exist yet.
            llm_client = LLMClient(config)

            # Symmetric with the worker branch above: the head can also be
            # the *responder* in an agent-initiated conversation (e.g. a
            # coordinator reaching out), not just the initiator of a
            # check-in - see dialogue.py. Unsolicited agent_message traffic
            # otherwise has nowhere to go once run_skill()/converse() stop
            # being the only thing listening on the global bus.
            dialogue = AgentDialogue(buses.global_bus, llm_client)

            def _global_default_handler(msg: dict) -> None:
                dialogue.handle(msg)

            buses.global_router.default_handler = _global_default_handler

            print("LLM-backed chat mode: type a message per line on stdin.", file=sys.stderr)

            def _log_event(event: dict) -> None:
                # Real-time audit trail: narration, tool calls, and tool
                # results as they happen, not just the final answer.
                print(json.dumps(event), file=sys.stderr)

            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    # Same local-blocking pattern as manual dispatch mode
                    # above - converse() is fire-and-forget, this REPL loop
                    # waits for one conversation's on_done before reading
                    # the next line.
                    done = threading.Event()
                    box: dict = {}

                    def on_done(result, error):
                        box["result"] = result
                        box["error"] = error
                        done.set()

                    head_mod.converse(
                        line, config, buses, skills, llm_client, on_done,
                        # Wrapped so the REPL's own trace also reaches the
                        # bus - see reasoning.py. Same events, one more
                        # destination.
                        on_event=reasoning.publishing_on_event(buses, inner=_log_event),
                        dialogue=dialogue,
                        max_turns=config.converse_max_turns,
                    )
                    done.wait()
                    if box["error"] is not None:
                        raise box["error"]
                    print(box["result"].answer)
                except Exception as exc:
                    print(json.dumps({"status": "error", "detail": str(exc)}))


if __name__ == "__main__":
    main()
