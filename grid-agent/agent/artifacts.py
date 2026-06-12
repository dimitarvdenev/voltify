"""Append-only step log for the UI."""

import json
import os


class StepWriter:
    def __init__(self, run_dir):
        os.makedirs(run_dir, exist_ok=True)
        self.path = os.path.join(run_dir, "steps.json")
        self.steps = []
        self._flush()

    def add(self, **step):
        step["step"] = len(self.steps) + 1
        self.steps.append(step)
        self._flush()

    def _flush(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.steps, f, indent=2)
        os.replace(tmp, self.path)
