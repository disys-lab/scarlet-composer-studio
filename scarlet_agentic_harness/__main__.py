"""
Entrypoint: python -m scarlet_agentic_harness

Role branch, same image either way (ROLE=head or ROLE=worker env var) -
see README for why. Not deployed anywhere yet; this is for local/manual runs
against a real Redis while building.
"""
import json
import sys

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.skills.registry import discover_skills
from scarlet_agentic_harness import head as head_mod
from scarlet_agentic_harness import worker as worker_mod


def main() -> None:
    config = HarnessConfig.from_env()
    buses = Buses(config)
    skills = discover_skills()

    if config.role == "worker":
        buses.report_status(capabilities=list(skills.keys()))
        print(f"[{config.agent_id}] worker online, skills={list(skills.keys())}", file=sys.stderr)
        while True:
            worker_mod.poll_once(config, buses, skills, timeout=1)
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
                    result = head_mod.run_skill(skill, req.get("params", {}), config, buses)
                    print(json.dumps(result))
                except Exception as exc:  # surfaced to the operator driving stdin manually
                    print(json.dumps({"status": "error", "detail": str(exc)}))
        else:
            raise NotImplementedError(
                "LLM tool-loop not yet implemented - awaiting real LLM_BASE_URL "
                "credentials per the user's stated plan."
            )


if __name__ == "__main__":
    main()
