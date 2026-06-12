"""Tool layer: Grid2Op env plus server-side action registry."""

import json
import os
import time

import grid2op
import numpy as np

from agent import config


class GridTools:
    def __init__(
        self,
        env_name=config.ENV_NAME,
        chronic_idx=config.DEMO_CHRONIC_IDX,
    ):
        dataset = env_name
        if not os.path.isabs(str(dataset)):
            dataset = os.path.join(config.GRID2OP_LOCAL_DIR, env_name)
        self.env = grid2op.make(dataset)
        self.env.set_id(chronic_idx)
        self.obs = self.env.reset()
        self.registry = {}
        self.meta = {}
        self.done = False

    def _line_summary(self, line_id):
        return {
            "line_id": int(line_id),
            "from_sub": int(self.obs.line_or_to_subid[line_id]),
            "to_sub": int(self.obs.line_ex_to_subid[line_id]),
            "rho": round(float(self.obs.rho[line_id]), 3),
        }

    def _scoped_subs(self, n_hops=1):
        """Substations at overloaded-line endpoints, grown by n hops."""
        over = np.where(self.obs.rho > 1.0)[0]
        subs = set()
        for line_id in over:
            subs.add(int(self.obs.line_or_to_subid[line_id]))
            subs.add(int(self.obs.line_ex_to_subid[line_id]))
        for _ in range(n_hops):
            grown = set(subs)
            for line_id in range(self.env.n_line):
                a = int(self.obs.line_or_to_subid[line_id])
                b = int(self.obs.line_ex_to_subid[line_id])
                if a in subs:
                    grown.add(b)
                if b in subs:
                    grown.add(a)
            subs = grown
        return sorted(subs)

    def get_grid_state(self):
        rho = self.obs.rho
        overloaded = np.where(rho > 1.0)[0]
        top = np.argsort(-rho)[: config.TOP_K_LOADED_LINES]
        return {
            "max_rho": round(float(rho.max()), 3),
            "n_overloaded": int(len(overloaded)),
            "overloaded_lines": [self._line_summary(line) for line in overloaded],
            "top_loaded_lines": [self._line_summary(line) for line in top],
            "disconnected_lines": [
                int(line) for line in np.where(~self.obs.line_status)[0]
            ],
            "candidate_scope_subs": self._scoped_subs(n_hops=1),
        }

    def _action_effects(self, act, sim_obs):
        reconnects = [
            int(line)
            for line in range(self.env.n_line)
            if not self.obs.line_status[line] and sim_obs.line_status[line]
        ]
        set_bus = act.set_bus
        switching_ops = int(
            np.sum((set_bus != 0) & (set_bus != self.obs.topo_vect))
        )
        return reconnects, switching_ops

    def search_topology_actions(self, substations, exclude_substations=None):
        excluded = set(exclude_substations or [])
        subs = [int(sub) for sub in substations if int(sub) not in excluded]
        t0 = time.time()
        results, skipped, n_tried = [], [], 0
        for sub_id in subs:
            acts = self.env.action_space.get_all_unitary_topologies_set(
                self.env.action_space, sub_id=sub_id
            )
            if len(acts) > config.MAX_ACTIONS_PER_SUB:
                skipped.append(
                    {"sub": sub_id, "reason": f"{len(acts)} combos, over cap"}
                )
                continue
            for i, act in enumerate(acts):
                sim_obs, _, sim_done, _ = self.obs.simulate(act)
                n_tried += 1
                if sim_done:
                    continue
                action_id = f"a-{sub_id:03d}-{i}"
                reconnects, n_ops = self._action_effects(act, sim_obs)
                self.registry[action_id] = act
                self.meta[action_id] = {
                    "action_id": action_id,
                    "substation": sub_id,
                    "description": f"bus-split at substation {sub_id}",
                    "simulated_max_rho": round(float(sim_obs.rho.max()), 3),
                    "simulated_n_overloaded": int((sim_obs.rho > 1.0).sum()),
                    "reconnects_lines": reconnects,
                    "switching_ops": n_ops,
                    "cost_class": "switching (~free)",
                }
                results.append(self.meta[action_id])
        results.sort(key=lambda result: result["simulated_max_rho"])
        return {
            "actions_simulated": n_tried,
            "actions_total_grid": self._total_unitary_actions(),
            "search_seconds": round(time.time() - t0, 1),
            "skipped_substations": skipped,
            "candidates": results[: config.TOP_K_CANDIDATES],
        }

    def _total_unitary_actions(self):
        return 72107

    def simulate_action(self, action_id):
        act = self.registry.get(action_id)
        if act is None:
            return {
                "error": f"unknown action_id {action_id!r}; "
                "run search_topology_actions first"
            }
        sim_obs, _, sim_done, _ = self.obs.simulate(act)
        if sim_done:
            return {"action_id": action_id, "diverged": True}
        reconnects, _ = self._action_effects(act, sim_obs)
        over = np.where(sim_obs.rho > 1.0)[0]
        return {
            "action_id": action_id,
            "diverged": False,
            "simulated_max_rho": round(float(sim_obs.rho.max()), 3),
            "simulated_n_overloaded": int(len(over)),
            "overloaded_lines": [int(line) for line in over],
            "reconnects_lines": reconnects,
        }

    def apply_action(self, action_id):
        act = self.registry.get(action_id)
        if act is None:
            return {
                "error": f"unknown action_id {action_id!r}; "
                "run search_topology_actions first"
            }
        self.obs, _, self.done, _ = self.env.step(act)
        if self.done:
            return {
                "applied": True,
                "game_over": True,
                "note": "grid collapsed after applying this action",
            }
        stable, worst_seen, steps = self._stability_check()
        return {
            "applied": True,
            "max_rho": round(float(self.obs.rho.max()), 3),
            "n_overloaded": int((self.obs.rho > 1.0).sum()),
            "stable_steps_checked": steps,
            "stable": stable,
            "worst_rho_during_check": round(worst_seen, 3),
        }

    def _stability_check(self):
        sim_env = self.env.copy()
        do_nothing = sim_env.action_space({})
        worst = float(self.obs.rho.max())
        for step in range(config.STABILITY_CHECK_STEPS):
            obs, _, done, _ = sim_env.step(do_nothing)
            if done:
                return False, worst, step + 1
            worst = max(worst, float(obs.rho.max()))
        return True, worst, config.STABILITY_CHECK_STEPS

    def dispatch(self, name, arguments):
        """Execute one tool call; always returns a compact JSON string."""
        if name not in (
            "get_grid_state",
            "search_topology_actions",
            "simulate_action",
            "apply_action",
        ):
            return json.dumps({"error": f"unknown tool {name!r}"})
        try:
            result = getattr(self, name)(**arguments)
        except TypeError as exc:
            result = {"error": f"bad arguments for {name}: {exc}"}
        out = json.dumps(result)
        if len(out) > config.MAX_TOOL_RESULT_CHARS:
            out = json.dumps({"truncated": True, "preview": out[:1400]})
        return out


TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_grid_state",
            "description": (
                "Current grid state: worst loadings, overloaded lines, "
                "disconnected lines, and a suggested search scope. All "
                "values from the power-flow solver."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_topology_actions",
            "description": (
                "Simulate every unitary bus-split at the given substations; "
                "returns candidates ranked by resulting max line loading. "
                "Keep scope small (<=8 substations) - the full grid has "
                "72,107 actions and cannot be searched in operator time."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "substations": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": (
                            "Substation ids to search, e.g. candidate_scope_subs "
                            "from get_grid_state."
                        ),
                    },
                    "exclude_substations": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": (
                            "Substations unavailable for switching, e.g. crew on site."
                        ),
                    },
                },
                "required": ["substations"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_action",
            "description": (
                "Simulate one candidate from a previous search against the "
                "current state. Solver results only."
            ),
            "parameters": {
                "type": "object",
                "properties": {"action_id": {"type": "string"}},
                "required": ["action_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_action",
            "description": (
                "Apply an action to the REAL grid, then verify stability over "
                "the next steps. Use only after simulating."
            ),
            "parameters": {
                "type": "object",
                "properties": {"action_id": {"type": "string"}},
                "required": ["action_id"],
            },
        },
    },
]
