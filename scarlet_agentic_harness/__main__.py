"""
Entrypoint: python -m scarlet_agentic_harness

Role branch, same image either way (ROLE=head or ROLE=worker env var) -
see README for why. Not deployed anywhere yet; this is for local/manual runs
against a real Redis while building.
"""
import json
import sys
import threading

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.cancellation import CancellationRegistry
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.dialogue import AgentDialogue
from scarlet_agentic_harness.llm.client import LLMClient
from scarlet_agentic_harness import observability
from scarlet_agentic_harness.skills.registry import discover_skills
from scarlet_agentic_harness import head as head_mod
from scarlet_agentic_harness import worker as worker_mod


def main() -> None:
    config = HarnessConfig.from_env()
    buses = Buses(config)
    skills = discover_skills()

    if config.role == "worker":
        buses.report_status(capabilities=list(skills.keys()))
        # Activity publishing (observability.py) is unconditional - it's
        # useful for a dashboard/human regardless of whether this worker
        # has LLM access. AgentDialogue is only constructed if an LLM
        # backend is configured - without one, agent_message traffic is
        # simply dropped (see worker.start_dispatch), same as any other
        # message nobody's set up to handle. Its context_fn now has real
        # grounding data to draw on: the registry's own in-flight
        # request_ids, not a placeholder.
        registry = CancellationRegistry(
            activity_mapper=observability.activity_mapper(config.app_id), agent_id=config.agent_id,
        )
        dialogue = (
            AgentDialogue(
                buses.global_bus, LLMClient(config),
                context_fn=lambda: {"in_flight_requests": registry.snapshot()},
            )
            if config.llm_base_url else None
        )
        worker_mod.start_dispatch(config, buses, skills, dialogue=dialogue, registry=registry)
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

                    head_mod.converse(line, config, buses, skills, llm_client, on_done, on_event=_log_event)
                    done.wait()
                    if box["error"] is not None:
                        raise box["error"]
                    print(box["result"].answer)
                except Exception as exc:
                    print(json.dumps({"status": "error", "detail": str(exc)}))


if __name__ == "__main__":
    main()
