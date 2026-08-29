"""
CombineSkill — the local, non-distributed arithmetic step that turns
already-computed skill results into a derived value (e.g. variance from
sum's S1, S2, n), without a dedicated skill per statistic.

This is deliberately generic rather than variance-specific: an earlier
design considered a CombineVarianceSkill with the formula baked in, which
defeats the point of a small composable skill library ("skills as
alphabets, agents build paragraphs" - see conversation history). Instead
the model itself supplies both the `expression` (e.g. "s2/n - (s1/n)**2")
and the `variables` it binds (e.g. {"s1": ..., "s2": ..., "n": ...}),
evaluated via safe_eval (AST-whitelisted, no eval(), no arbitrary code).

contribute() is a no-op: combine has no per-worker local data to gather, so
every worker asked to "contribute" simply does nothing. coordinate() does
the one and only real work, on a single randomly-chosen worker per Skill's
base coordinator_for() default - the head supplies the expression and
values but never evaluates them itself ("head never computes" - see
conversation history on why this generalizes past Federator-backed skills
too). No readiness handshake is needed here (unlike median/sum): combine
depends on nothing from peer workers, only on the values already handed to
it in the request, so coordinate() can answer immediately without touching
the local bus at all.
"""
from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.skills.base import Skill
from scarlet_agentic_harness.skills.safe_eval import SafeEvalError, safe_eval


class CombineSkill(Skill):
    name = "combine"
    description = (
        "Evaluate a numeric arithmetic expression against a set of named "
        "variables, typically the results of earlier skill calls (e.g. sum's "
        "result and n). Use this to derive values like mean or variance from "
        "already-computed building blocks instead of assuming a dedicated "
        "skill exists for every statistic. Supports +, -, *, /, ** and unary "
        "+/- only - no function calls, attribute access, or anything beyond "
        "plain arithmetic."
    )
    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": (
                    "An arithmetic expression using only the names given in "
                    "`variables`, e.g. \"s2/n - (s1/n)**2\" for variance given "
                    "s1=sum(x), s2=sum(x^2), n=count."
                ),
            },
            "variables": {
                "type": "object",
                "description": "Name -> numeric value bindings referenced by `expression`.",
                "additionalProperties": {"type": "number"},
            },
        },
        "required": ["expression", "variables"],
    }

    def contribute(self, ctx: HarnessContext, request: dict) -> None:
        pass  # no per-worker data to gather - see module docstring

    def coordinate(self, ctx: HarnessContext, request: dict, workers: list[str]) -> dict:
        params = request.get("params", {})
        expression = params.get("expression")
        variables = params.get("variables", {})
        if not expression:
            return {"status": "error", "detail": "combine requires a non-empty `expression`"}
        try:
            result = safe_eval(expression, variables)
        except SafeEvalError as exc:
            return {"status": "error", "detail": f"invalid expression: {exc}"}
        return {
            "status": "ok",
            "result": result,
            "detail": f"combine: {expression} = {result} (evaluated on {ctx.agent_id})",
        }
