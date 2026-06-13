import json
from types import SimpleNamespace as NS

from agent.llm import _promises_tool_without_call, run_loop


def fake_response(content=None, tool_calls=None):
    return NS(
        choices=[
            NS(
                message=NS(
                    role="assistant",
                    content=content,
                    tool_calls=tool_calls,
                )
            )
        ]
    )


def fake_tool_call(call_id, name, args):
    return NS(
        id=call_id,
        type="function",
        function=NS(name=name, arguments=json.dumps(args)),
    )


def make_fake_client(script):
    state = {"i": 0, "seen_messages": []}

    def create(**kwargs):
        state["seen_messages"] = list(kwargs["messages"])
        resp = script[state["i"]]
        state["i"] += 1
        return resp

    client = NS(chat=NS(completions=NS(create=create)))
    return client, state


def test_loop_executes_tools_then_returns_narration():
    script = [
        fake_response(
            tool_calls=[fake_tool_call("c1", "get_grid_state", {})]
        ),
        fake_response(content="Line 177 is overloaded; I will search."),
        fake_response(
            tool_calls=[
                fake_tool_call("c2", "search_topology_actions", {"substations": [67]})
            ]
        ),
        fake_response(content="Found a switching candidate."),
    ]
    client, state = make_fake_client(script)
    calls = []

    def dispatch(name, args):
        calls.append((name, args))
        return json.dumps({"max_rho": 1.30})

    events = []
    final = run_loop(
        client,
        "test-model",
        [{"role": "user", "content": "grid status?"}],
        tools_schema=[],
        dispatch=dispatch,
        on_event=lambda kind, payload: events.append(kind),
    )

    assert final == "Found a switching candidate."
    assert calls == [
        ("get_grid_state", {}),
        ("search_topology_actions", {"substations": [67]}),
    ]
    roles = [
        message["role"] if isinstance(message, dict) else "assistant"
        for message in state["seen_messages"]
    ]
    assert "tool" in roles
    assert events == ["tool", "narration", "tool", "narration"]


def test_loop_stops_at_max_iterations():
    looping = fake_response(
        tool_calls=[fake_tool_call("c1", "get_grid_state", {})]
    )
    client, _ = make_fake_client([looping] * 20)
    final = run_loop(
        client,
        "test-model",
        [{"role": "user", "content": "x"}],
        tools_schema=[],
        dispatch=lambda name, args: "{}",
        max_iterations=3,
    )
    assert "iteration limit" in final


def test_promised_tool_detector_handles_now_variant():
    assert _promises_tool_without_call(
        "I will now search for topology switching actions to alleviate this overload."
    )
