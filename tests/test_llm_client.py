"""
LLMClient's to/from-wire translation, tested against a mocked openai client
object (mimicking the real SDK's response shape) - not a live backend, since
no credentials exist yet. This is the piece that will need re-verifying
against a real endpoint once litellm credentials are available; until then,
this proves the translation logic itself is internally consistent.
"""
import json
from types import SimpleNamespace

from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.llm.client import LLMClient, _from_wire, _to_wire


def _config():
    return HarnessConfig(
        role="head", app_id="x", node_address="n", device_group="d", head_bus="h",
        llm_base_url="http://fake", llm_api_key=None, llm_model="fake-model",
    )


def test_llm_client_requires_base_url():
    cfg = HarnessConfig(
        role="head", app_id="x", node_address="n", device_group="d", head_bus="h",
        llm_base_url=None, llm_api_key=None, llm_model=None,
    )
    try:
        LLMClient(cfg)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_to_wire_plain_user_message():
    assert _to_wire({"role": "user", "content": "hi"}) == {"role": "user", "content": "hi"}


def test_to_wire_assistant_with_tool_calls_json_encodes_arguments():
    canonical = {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "c1", "name": "median", "arguments": {"n": 3}}],
    }
    wire = _to_wire(canonical)
    assert wire["tool_calls"][0]["function"]["name"] == "median"
    # arguments must be a JSON *string* on the wire, not a dict - that's the
    # actual OpenAI tool-call schema
    assert wire["tool_calls"][0]["function"]["arguments"] == json.dumps({"n": 3})
    assert json.loads(wire["tool_calls"][0]["function"]["arguments"]) == {"n": 3}


def test_to_wire_tool_result_json_encodes_content():
    canonical = {"role": "tool", "tool_call_id": "c1", "content": {"status": "ok", "result": 4.5}}
    wire = _to_wire(canonical)
    assert wire["role"] == "tool"
    assert wire["tool_call_id"] == "c1"
    assert json.loads(wire["content"]) == {"status": "ok", "result": 4.5}


def test_from_wire_no_tool_calls():
    fake_message = SimpleNamespace(content="just an answer", tool_calls=None)
    canonical = _from_wire(fake_message)
    assert canonical == {"role": "assistant", "content": "just an answer", "tool_calls": []}


def test_from_wire_with_tool_calls_parses_json_arguments():
    fake_tool_call = SimpleNamespace(
        id="call_abc",
        function=SimpleNamespace(name="median", arguments=json.dumps({"foo": "bar"})),
    )
    fake_message = SimpleNamespace(content=None, tool_calls=[fake_tool_call])
    canonical = _from_wire(fake_message)
    assert canonical == {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "call_abc", "name": "median", "arguments": {"foo": "bar"}}],
    }


def test_from_wire_empty_arguments_string_becomes_empty_dict():
    # real backends sometimes send "" instead of "{}" for a no-arg tool call
    fake_tool_call = SimpleNamespace(id="c1", function=SimpleNamespace(name="median", arguments=""))
    fake_message = SimpleNamespace(content=None, tool_calls=[fake_tool_call])
    canonical = _from_wire(fake_message)
    assert canonical["tool_calls"][0]["arguments"] == {}


def test_chat_roundtrips_through_a_mocked_openai_client(monkeypatch):
    """End-to-end through LLMClient.chat() itself, with the real OpenAI()
    client swapped for a mock that returns a scripted response shaped like
    the real SDK's - proves the whole chat() method wires _to_wire/_from_wire
    together correctly, not just the helpers in isolation."""
    fake_tool_call = SimpleNamespace(id="c1", function=SimpleNamespace(name="median", arguments="{}"))
    fake_message = SimpleNamespace(content=None, tool_calls=[fake_tool_call])
    fake_response = SimpleNamespace(choices=[SimpleNamespace(message=fake_message)])

    captured_kwargs = {}

    class _FakeCompletions:
        def create(self, **kwargs):
            captured_kwargs.update(kwargs)
            return fake_response

    class _FakeChat:
        completions = _FakeCompletions()

    client = LLMClient(_config())
    client._client = SimpleNamespace(chat=_FakeChat())

    result = client.chat(
        [{"role": "user", "content": "what's the median?"}],
        tools=[{"type": "function", "function": {"name": "median", "parameters": {}}}],
    )

    assert result == {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "name": "median", "arguments": {}}]}
    assert captured_kwargs["model"] == "fake-model"
    assert captured_kwargs["messages"] == [{"role": "user", "content": "what's the median?"}]
    assert captured_kwargs["tools"][0]["function"]["name"] == "median"
