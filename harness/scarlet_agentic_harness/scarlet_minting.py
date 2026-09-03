"""
Lets a worker mint its own ad hoc scarlet mid-task, via real LLM reasoning -
distinct from both head.py's dispatch-time pre-registration (_register_scarlets,
which mints scarlets a skill's *author* already declared in code via
Skill.scarlet_names(), only generating the description) and from a plain
ctx.mapper()/ctx.federator() call (fully static, no reasoning at all).

This exists for the case a skill's own contribute()/coordinate() genuinely
doesn't know in advance whether or what shared state it will need until
it's actually running - e.g. deciding whether an intermediate result is
worth publishing for another agent to discover. Deliberately narrower than
head.converse()'s tool-calling loop: exactly one tool (mint_scarlet), one
turn, no multi-turn conversation, and the caller supplies the whole
situation up front via `motivation` rather than an open-ended human
message - this is one bounded decision inside a larger, already-running
skill, not a general-purpose agent loop.

What's still NOT handed to the LLM: whether to mint at all. That's the
calling skill's own code decision (it calls mint_scarlet() or it doesn't) -
see worker.py's module docstring for why skill *selection* stays head-only
and deterministic. Only the concrete name/type/description of a scarlet the
skill has already decided it needs is real LLM reasoning.

Handing the LLM the *name* here (not just the description, unlike head's
dispatch-time registration - see head.py's Skill.scarlet_names() docstring
for why the head case specifically can't) is safe for this narrower case
because the same call that invents the name is also what the caller uses
immediately after for its own Map()/AllGather() calls - see
HarnessContext.mint_scarlet(). Nothing else in the system has a
competing, independently-hardcoded expectation for this particular name,
which is exactly the property that made LLM-invented names unsafe for
head's dispatch-time registration.

SCARLET_TUTORIAL (below) is sent as part of every mint_scarlet_with_reasoning()
call - grounding in what a scarlet actually is (mapper vs. messenger,
what Federator adds, why the description matters) rather than expecting
the model to infer that from the tool schema's one-line field
descriptions alone. One tutorial, one place, used by both entry points
(HarnessContext.mint_scarlet() and CreateScarletSkill) rather than
duplicated into each.
"""
from typing import Protocol


class ChatClient(Protocol):
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict: ...


# Grounded in the real scarlets primitives (scarlets/core/Mapper.py,
# scarlets/formulations/Federator.py, scarlets/messaging/Messenger.py,
# ScarletUtils.register_scarlet_definition) - not a generic description of
# "shared storage". This is sent to the model every time it's asked to
# mint a scarlet, so its name/type/description choices are grounded in
# what these things actually are and do, not guessed from the tool
# schema's one-line field descriptions alone.
SCARLET_TUTORIAL = """
A scarlet is a named, Redis-backed primitive that lets independently-running
agents - each its own process, sharing no memory - exchange or aggregate
data with each other. Once you register one, its definition (name, type,
attributes, and the description you write) is stored in Redis and fed
directly into every other agent's context window - that's the only way
another agent learns it exists and how to use it, so get the description
right.

Two scarlet types:
  - "mapper": a shared key-value store. Any agent can Map(value, key) to
    write its own contribution under its own key, and AllGather() to read
    every agent's contribution back at once. Use this whenever agents each
    hold a piece of data that needs to be collected or combined - a local
    partition, a partial result, an intermediate artifact worth publishing.
    A mapper-type scarlet can also back a Federator, a specialized mapper
    for associative reductions (sum, and anything built from it): every
    contributor Maps its local value once, then one coordinator Aggregates
    all of them with an operation like SUM in a single round trip, instead
    of every agent reading and manually combining every other agent's
    value.
  - "messenger": point-to-point/broadcast messaging (Send/Receive/
    Broadcast) plus liveness and capability reporting (ReportStatus/
    GatherStatus). Use this for coordination and signaling traffic, not
    for storing or aggregating data itself.

Choose "mapper" for anything that holds or aggregates actual data (a
vector, a matrix, a tensor, a scalar, a partial result); choose "messenger"
only when the point is passing messages or announcing status, not storing
a value.

Your description is the single most load-bearing field: it is the entire
contract another agent gets before deciding to use this scarlet. State
concretely - what the data represents, its shape (a scalar? a vector of
what length? a matrix of what dimensions?), any key convention (e.g. "keyed
by each contributing agent's own agent id"), and how it should be read or
written. "Stores some values" tells another agent nothing useful; "holds
each worker's local sorted partition, keyed by agent id, for a coordinator
to AllGather and merge" tells them exactly what to expect.
""".strip()


MINT_SCARLET_TOOL = {
    "type": "function",
    "function": {
        "name": "mint_scarlet",
        "description": (
            "Register a new scarlet - a shared, Redis-backed bucket other agents can "
            "discover and read the contract of. Choose the name, type, and description "
            "yourself, grounded in what you were just taught about what scarlets are and "
            "how they're used. The description is fed directly into other agents' context "
            "windows, so be concrete: what the data holds, its shape, how it should be "
            "read or written."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "A short, descriptive name, unique to this bucket's purpose - used verbatim as the Redis key.",
                },
                "scarlet_type": {
                    "type": "string",
                    "enum": ["mapper", "messenger"],
                    "description": (
                        "'mapper' for shared key-value storage or aggregation of actual data "
                        "(a vector/matrix/tensor/scalar/partial result) - almost always the "
                        "right choice for a mathematical artifact. 'messenger' only for "
                        "message-passing/coordination traffic, not data storage."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": (
                        "Natural-language contract: what this holds, its shape, any key "
                        "convention, and how other agents should read or write it. This is "
                        "the only thing another agent sees before using it - be concrete, not "
                        "generic."
                    ),
                },
            },
            "required": ["name", "scarlet_type", "description"],
        },
    },
}


class ScarletMintingFailed(RuntimeError):
    """Raised when the model doesn't call mint_scarlet (or calls anything
    else - there is only one tool offered, so anything else is a hard
    failure, not a case to silently paper over). Unlike head's
    description-only generation, there is no safe template fallback here:
    a generic *description* is low-stakes, but an ad hoc scarlet has no
    safe default *name* to fall back to."""


def mint_scarlet_with_reasoning(llm_client: ChatClient, agent_id: str, motivation: str) -> str:
    """
    One bounded LLM tool-call turn: given `motivation` (why the calling
    skill decided, in its own code, that a new scarlet is needed right
    now), the model picks the tool's arguments and this function registers
    exactly what it chose - real reasoning over the specifics, not a
    template. Returns the registered name; the caller MUST use this return
    value for any subsequent Map()/AllGather() call rather than a
    separately hardcoded string, or the two can drift (see module
    docstring's discussion of why that's safe here specifically).
    """
    # Deferred import: this module doesn't otherwise depend on the scarlets
    # package, and importing at call time keeps that dependency scoped to
    # the one function that actually needs it.
    from scarlets.utils.ScarletUtils import register_scarlet_definition

    turn = llm_client.chat(
        [{
            "role": "user",
            "content": (
                f"{SCARLET_TUTORIAL}\n\n"
                f"You are agent {agent_id!r}, currently executing a task. {motivation}\n\n"
                f"Call mint_scarlet with the name, type, and description for the scarlet "
                f"you need."
            ),
        }],
        tools=[MINT_SCARLET_TOOL],
    )
    calls = turn.get("tool_calls") or []
    if not calls or calls[0]["name"] != "mint_scarlet":
        raise ScarletMintingFailed(f"model did not call mint_scarlet: {turn!r}")

    args = calls[0]["arguments"]
    name = args.get("name")
    if not name:
        raise ScarletMintingFailed(f"model called mint_scarlet without a usable name: {args!r}")

    register_scarlet_definition(
        scarlet_name=name,
        scarlet_type=args.get("scarlet_type") or "mapper",
        description=args.get("description", ""),
        attributes={"mode": "redis-scarlet"},
        overwrite=True,
    )
    return name
