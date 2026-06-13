"""Append-only step log for the UI."""

import json
import os
import threading

from agent.advisors.blackboard import Blackboard


class StepWriter:
    def __init__(self, run_dir):
        os.makedirs(run_dir, exist_ok=True)
        self.path = os.path.join(run_dir, "steps.json")
        self.blackboard = Blackboard(run_dir)
        self.blackboard.reset()
        self.steps = []
        # The operator loop and the EventInjector thread both append steps.
        self._lock = threading.Lock()
        self._flush()

    def add(self, **step):
        with self._lock:
            step["step"] = len(self.steps) + 1
            step.setdefault("agent", _agent_for_step(step))
            self.steps.append(step)
            self._flush()

    def _flush(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.steps, f, indent=2)
        os.replace(tmp, self.path)


def _agent_for_step(step):
    if "agent" in step:
        return step["agent"]
    if step.get("kind") == "operator":
        return "operator"
    return "ops"
