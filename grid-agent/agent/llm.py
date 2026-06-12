"""Plain OpenAI chat-completions tool loop."""

import json

from agent import config


def make_client():
    from openai import OpenAI

    return OpenAI(base_url=config.LLM_BASE_URL, api_key="local")


def _assistant_to_dict(message):
    out = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        out["tool_calls"] = [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                },
            }
            for tool_call in message.tool_calls
        ]
    return out


def run_loop(
    client,
    model,
    messages,
    tools_schema,
    dispatch,
    max_iterations=config.MAX_LOOP_ITERATIONS,
    on_event=None,
):
    """Run tool calls until the model produces plain text."""
    emit = on_event or (lambda kind, payload: None)
    for _ in range(max_iterations):
        resp = client.chat.completions.create(
            model=model, messages=messages, tools=tools_schema
        )
        message = resp.choices[0].message
        messages.append(_assistant_to_dict(message))
        text = (message.content or "").strip()
        if not message.tool_calls:
            emit("narration", {"text": text})
            return text
        # Narration may accompany tool calls; surface it so the reasoning
        # behind each step still reaches the feed instead of being dropped.
        if text:
            emit("narration", {"text": text})
        for tool_call in message.tool_calls:
            try:
                args = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = dispatch(tool_call.function.name, args)
            emit(
                "tool",
                {
                    "tool": tool_call.function.name,
                    "arguments": args,
                    "result": result,
                },
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                }
            )
    text = (
        "Stopped: iteration limit reached without a final answer. "
        "Grid state may still need attention."
    )
    emit("narration", {"text": text})
    return text
