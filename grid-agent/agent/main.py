"""Demo entrypoint.

  .venv/bin/python -m agent.main
  .venv/bin/python -m agent.main --inbox
"""

import argparse
import json
import os
import time

from agent import config
from agent.advisors import weather
from agent.advisors.blackboard import Blackboard
from agent.advisors.injector import EventInjector
from agent.artifacts import StepWriter
from agent.llm import make_client, run_loop
from agent.prompts import SCENARIO_BRIEF, SYSTEM_PROMPT
from agent.render import GridRenderer
from agent.tools import TOOLS_SCHEMA, GridTools


class Inbox:
    """Operator messages from artifacts/run/inbox.json."""

    def __init__(self, run_dir):
        self.path = os.path.join(run_dir, "inbox.json")
        self.consumed = 0
        if not os.path.exists(self.path):
            with open(self.path, "w") as f:
                json.dump([], f)
        self.blackboard = Blackboard(run_dir)

    def next_message(self):
        while True:
            try:
                with open(self.path) as f:
                    items = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                items = []
            if len(items) > self.consumed:
                item = items[self.consumed]
                self.consumed += 1
                if item.get("kind") == "decision":
                    self.blackboard.append("decisions", item)
                    message = "Operator decision: " + json.dumps(item, separators=(",", ":"))
                else:
                    message = item.get("text", "")
                return message
            time.sleep(0.5)


def main():
    args = _parse_args()
    tools = GridTools()
    client = make_client()
    writer = StepWriter(config.RUN_DIR)
    renderer = GridRenderer(tools.env.observation_space, config.RENDER_DIR)
    inbox = Inbox(config.RUN_DIR) if args.inbox else None

    emit_render = _render_emitter(tools, renderer)
    _write_opening_entry(writer, tools, emit_render)
    weather_bulletin = _publish_weather(args, tools, writer, client)
    messages = _initial_messages(weather_bulletin)
    on_event = _event_handler(tools, writer, emit_render)
    injector = _start_injector(args, tools, writer, emit_render, client)
    try:
        _operator_loop(inbox, messages, writer, client, tools, on_event)
    finally:
        if injector:
            injector.stop()


def _parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inbox",
        action="store_true",
        help="read operator messages from UI inbox file",
    )
    parser.add_argument(
        "--no-weather",
        action="store_true",
        help="skip the Weather advisor's derate bulletin at session open",
    )
    parser.add_argument(
        "--inject",
        action="store_true",
        help="run the random event injector: autonomous grid dynamics "
        "(forced outages, load drift, derates) between operator turns",
    )
    parser.add_argument(
        "--inject-period",
        type=float,
        default=config.INJECTOR_PERIOD_SEC,
        help="mean seconds between injected events (default %(default)s)",
    )
    return parser.parse_args()


def _render_emitter(tools, renderer):
    def emit_render(tag):
        # Lock so a render never reads obs mid env-step and two renders
        # (operator loop vs injector) never run concurrently.
        with tools.lock:
            scope = tools.get_grid_state()["candidate_scope_subs"] or None
            full, zoom = renderer.render(tools.obs, tag, focus_subs=scope)
        return _artifact_relpath(full), _artifact_relpath(zoom)

    return emit_render


def _write_opening_entry(writer, tools, emit_render):
    full, zoom = emit_render("step_0_open")
    writer.add(
        kind="narration",
        text="Connected to grid.",
        grid_status=_grid_status(tools),
        max_rho=round(float(tools.obs.rho.max()), 3),
        render_full=full,
        render_zoom=zoom,
    )


def _publish_weather(args, tools, writer, client):
    if args.no_weather:
        return None
    # Reactive Weather advisor: posts derate constraints to the blackboard
    # before the Ops agent's first look at the grid.
    _, bulletin = weather.publish(tools.blackboard, client)
    writer.add(
        kind="constraint",
        agent="weather",
        text=bulletin,
        grid_status=_grid_status(tools),
        max_rho=round(float(tools.obs.rho.max()), 3),
    )
    print(f"\nweather> {bulletin}\n")
    return bulletin


def _event_handler(tools, writer, emit_render):
    def on_event(kind, payload):
        entry = {
            "kind": kind,
            "agent": "ops",
            "grid_status": _grid_status(tools),
            "max_rho": round(float(tools.obs.rho.max()), 3),
        }
        if kind == "tool":
            entry["tool"] = payload["tool"]
            entry["arguments"] = payload["arguments"]
            entry["summary"] = payload["result"][:200]
            if payload["tool"] == "screen_post_action":
                entry["agent"] = "screening"
                entry["kind"] = "verdict"
                entry["text"] = _screening_feed_text(payload["result"])
            if payload["tool"] == "check_asset_health":
                entry["agent"] = "asset_health"
                entry["kind"], entry["text"] = _asset_feed(payload["result"])
            if payload["tool"] == "apply_action":
                tag = f"step_{len(writer.steps)}_applied"
                entry["render_full"], entry["render_zoom"] = emit_render(tag)
        else:
            entry["text"] = payload["text"]
        writer.add(**entry)

    return on_event


def _initial_messages(weather_bulletin):
    brief = SCENARIO_BRIEF
    if weather_bulletin:
        brief += f"\nAdvisor bulletin (Weather): {weather_bulletin}\n"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": brief},
    ]


def _start_injector(args, tools, writer, emit_render, client):
    if not args.inject:
        return None
    injector = EventInjector(
        tools,
        writer,
        render_fn=emit_render,
        client=client,
        period=args.inject_period,
    )
    injector.start()
    print(f"\nevents> injector live (~{args.inject_period:.0f}s cadence)\n")
    return injector


def _operator_loop(inbox, messages, writer, client, tools, on_event):
    print("Operator console. Type message (or 'quit').")
    while True:
        operator_msg = _next_operator_message(inbox)
        if operator_msg.lower() in ("quit", "exit"):
            break
        if not operator_msg:
            continue
        _append_operator_message(messages, operator_msg)
        writer.add(kind="operator", text=operator_msg)
        writer.set_busy("Operations agent reasoning…")
        try:
            final = run_loop(
                client,
                config.LLM_MODEL,
                messages,
                TOOLS_SCHEMA,
                tools.dispatch,
                on_event=on_event,
            )
        finally:
            writer.clear_busy()
        print(f"\nagent> {final}\n")


def _next_operator_message(inbox):
    if inbox:
        return inbox.next_message()
    return input("operator> ").strip()


def _append_operator_message(messages, operator_msg):
    if len(messages) > 2 or messages[-1]["role"] != "user":
        messages.append({"role": "user", "content": operator_msg})
    else:
        messages[-1]["content"] += "\n\nOperator: " + operator_msg


def _grid_status(tools):
    return "rescued" if tools.obs.rho.max() < 1.0 else "overloaded"


def _asset_feed(result_json):
    try:
        result = json.loads(result_json)
    except json.JSONDecodeError:
        return "verdict", result_json
    if "error" in result:
        return "verdict", "Asset Health error: " + result["error"]
    kind = "veto" if result.get("verdict") == "block" else "verdict"
    return kind, result.get("narration", "")


def _artifact_relpath(path):
    return os.path.relpath(path, config.ROOT)


def _screening_feed_text(result_json):
    try:
        result = json.loads(result_json)
    except json.JSONDecodeError:
        return result_json
    if "error" in result:
        return "Screening error: " + result["error"]
    if result.get("n1_secure"):
        verdict = "N-1 secure"
    elif result.get("n1_not_worse"):
        verdict = "N-1 not worsened (pre-existing fragilities only)"
    else:
        verdict = "HOLD - fix introduces new N-1 fragilities"
    worst = result.get("worst_next_contingency") or {}
    line = worst.get("line_label") or f"line {worst.get('line_id')}"
    if worst.get("diverged"):
        consequence = "diverges"
    else:
        consequence = f"reaches max rho {worst.get('post_trip_rho')}"
    return (
        f"{verdict}: screened {result.get('screened_outages')} post-action "
        f"outages for {result.get('action_id')}. Worst next contingency is "
        f"{line}: {consequence}. {result.get('baseline_comparison')}"
    )


if __name__ == "__main__":
    main()
