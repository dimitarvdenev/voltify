"""Shared file-backed blackboard for advisor verdicts and constraints."""

import json
import os
from copy import deepcopy


DEFAULT_BLACKBOARD = {
    "constraints": [],
    "vetoes": [],
    "quotes": [],
    "screening_verdicts": [],
    "availability": [],
    "clock": None,
    "decisions": [],
}


class Blackboard:
    def __init__(self, run_dir):
        self.path = os.path.join(run_dir, "blackboard.json")
        os.makedirs(run_dir, exist_ok=True)
        if not os.path.exists(self.path):
            self.reset()

    def reset(self):
        self.write(deepcopy(DEFAULT_BLACKBOARD))

    def read(self):
        try:
            with open(self.path) as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        board = deepcopy(DEFAULT_BLACKBOARD)
        board.update(data)
        return board

    def write(self, board):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(board, f, indent=2)
        os.replace(tmp, self.path)

    def append(self, key, item):
        board = self.read()
        board.setdefault(key, []).append(item)
        self.write(board)
        return board
