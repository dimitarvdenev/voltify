"""Demo entrypoint.

  .venv/bin/python -m agent.main
  .venv/bin/python -m agent.main --inbox
"""

import argparse
import json
import os
import time

from agent import config
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

    def next_message(self):
        while True:
            try:
                with open(self.path) as f:
                    items = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                items = []
            if len(items) > self.consumed:
                message = items[self.consumed]["text"]
                self.consumed += 1
                return message
            time.sleep(0.5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inbox",
        action="store_true",
        help="read operator messages from UI inbox file",
    )
    args = parser.parse_args()

    tools = GridTools()
    client = make_client()
    writer = StepWriter(config.RUN_DIR)
    renderer = GridRenderer(tools.env.observation_space, config.RENDER_DIR)
    inbox = Inbox(config.RUN_DIR) if args.inbox else None

    def grid_status():
        return "rescued" if tools.obs.rho.max() < 1.0 else "overloaded"

    def emit_render(tag):
        scope = tools.get_grid_state()["candidate_scope_subs"] or None
        full, zoom = renderer.render(tools.obs, tag, focus_subs=scope)
        rel = lambda path: os.path.relpath(path, config.ROOT)
        return rel(full), rel(zoom)

    full, zoom = emit_render("step_0_open")
    writer.add(
        kind="narration",
        text="Connected to grid.",
        grid_status=grid_status(),
        max_rho=round(float(tools.obs.rho.max()), 3),
        render_full=full,
        render_zoom=zoom,
    )

    def on_event(kind, payload):
        entry = {
            "kind": kind,
            "grid_status": grid_status(),
            "max_rho": round(float(tools.obs.rho.max()), 3),
        }
        if kind == "tool":
            entry["tool"] = payload["tool"]
            entry["summary"] = payload["result"][:200]
            if payload["tool"] == "apply_action":
                tag = f"step_{len(writer.steps)}_applied"
                entry["render_full"], entry["render_zoom"] = emit_render(tag)
        else:
            entry["text"] = payload["text"]
        writer.add(**entry)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": SCENARIO_BRIEF},
    ]

    print("Operator console. Type message (or 'quit').")
    while True:
        if inbox:
            operator_msg = inbox.next_message()
        else:
            operator_msg = input("operator> ").strip()
        if operator_msg.lower() in ("quit", "exit"):
            break
        if not operator_msg:
            continue
        if len(messages) > 2 or messages[-1]["role"] != "user":
            messages.append({"role": "user", "content": operator_msg})
        else:
            messages[-1]["content"] += "\n\nOperator: " + operator_msg
        writer.add(kind="operator", text=operator_msg)
        final = run_loop(
            client,
            config.LLM_MODEL,
            messages,
            TOOLS_SCHEMA,
            tools.dispatch,
            on_event=on_event,
        )
        print(f"\nagent> {final}\n")


if __name__ == "__main__":
    main()
