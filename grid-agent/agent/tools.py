"""Tool layer: Grid2Op env plus server-side action registry."""

import json
import os
import threading
import time

import grid2op
import numpy as np

from agent import config
from agent.advisors.asset_health import AssetHealth, narrate as asset_narrate, veto_item
from agent.advisors.blackboard import Blackboard
from agent.advisors.screening import screen_post_action_env
from agent.labels import line_label, substation_label


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
        # Guards self.env / self.obs against concurrent access by the
        # operator loop (apply_action) and the EventInjector thread.
        self.lock = threading.RLock()
        self.registry = {}
        self.meta = {}
        self.done = False
        self.blackboard = Blackboard(config.RUN_DIR)
        self.asset_health = AssetHealth()
        self.asset_checked = {}
        self.screened = {}
        self._baseline_screen = None

    def _degree(self):
        degree = [0 for _ in range(self.env.n_sub)]
        for line_id in range(self.env.n_line):
            degree[int(self.obs.line_or_to_subid[line_id])] += 1
            degree[int(self.obs.line_ex_to_subid[line_id])] += 1
        return degree

    def _incident_rho(self, obs=None):
        obs = obs or self.obs
        incident = [0.0 for _ in range(self.env.n_sub)]
        for line_id, rho in enumerate(obs.rho):
            a = int(obs.line_or_to_subid[line_id])
            b = int(obs.line_ex_to_subid[line_id])
            incident[a] = max(incident[a], float(rho))
            incident[b] = max(incident[b], float(rho))
        return incident

    def _substation_label(self, sub_id, obs=None):
        degree = self._degree()
        incident = self._incident_rho(obs)
        return substation_label(int(sub_id), degree[int(sub_id)], incident[int(sub_id)])

    def _line_summary(self, line_id, obs=None):
        obs = obs or self.obs
        from_sub = int(obs.line_or_to_subid[line_id])
        to_sub = int(obs.line_ex_to_subid[line_id])
        from_label = self._substation_label(from_sub, obs)
        to_label = self._substation_label(to_sub, obs)
        return {
            "line_id": int(line_id),
            "line_label": line_label(line_id, from_label, to_label),
            "from_sub": from_sub,
            "to_sub": to_sub,
            "rho": round(float(obs.rho[line_id]), 3),
        }

    def _substation_summary(self, sub_id, obs=None):
        return {"sub": int(sub_id), "label": self._substation_label(sub_id, obs)}

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

    def _derate_map(self, board):
        """line_id -> derate pct from weather constraints on the blackboard."""
        derates = {}
        for item in board.get("constraints", []):
            if item.get("kind") == "derate" and item.get("line_id") is not None:
                derates[int(item["line_id"])] = float(item["pct"])
        return derates

    def _apply_derates(self, summary, derates):
        pct = derates.get(summary["line_id"])
        if pct is not None:
            summary["derate_pct"] = pct
            summary["effective_rho"] = round(
                summary["rho"] / (1.0 - pct / 100.0), 3
            )
        return summary

    def get_grid_state(self):
        rho = self.obs.rho
        overloaded = np.where(rho > 1.0)[0]
        top = np.argsort(-rho)[: config.TOP_K_LOADED_LINES]
        board = self.blackboard.read()
        derates = self._derate_map(board)
        state = {
            "max_rho": round(float(rho.max()), 3),
            "n_overloaded": int(len(overloaded)),
            "overloaded_lines": [
                self._apply_derates(self._line_summary(line), derates)
                for line in overloaded
            ],
            "top_loaded_lines": [
                self._apply_derates(self._line_summary(line), derates)
                for line in top
            ],
            "disconnected_lines": [
                int(line) for line in np.where(~self.obs.line_status)[0]
            ],
            "candidate_scope_subs": self._scoped_subs(n_hops=1),
            "blackboard": _compact_blackboard(board),
        }
        if derates:
            effective = [
                float(rho[line]) / (1.0 - pct / 100.0)
                for line, pct in derates.items()
            ]
            state["max_effective_rho"] = round(
                max(state["max_rho"], max(effective)), 3
            )
            state["derate_note"] = (
                "weather derate active: effective_rho is the binding "
                "loading on derated lines, not nameplate rho"
            )
        return state

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
        subs = []
        skipped = []
        for raw_sub in substations:
            sub = int(raw_sub)
            if sub in excluded:
                continue
            if sub < 0 or sub >= self.env.n_sub:
                skipped.append({"sub": sub, "label": f"Unknown UW {sub}", "reason": "invalid substation id"})
                continue
            subs.append(sub)
        t0 = time.time()
        results, n_tried = [], 0
        for sub_id in subs:
            acts = self.env.action_space.get_all_unitary_topologies_set(
                self.env.action_space, sub_id=sub_id
            )
            if len(acts) > config.MAX_ACTIONS_PER_SUB:
                skipped.append(
                    {
                        "sub": sub_id,
                        "label": self._substation_label(sub_id),
                        "reason": f"{len(acts)} combos, over cap",
                    }
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
                    "substation_label": self._substation_label(sub_id),
                    "description": f"bus-split at {self._substation_label(sub_id)}",
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
            "overloaded_line_details": [
                self._line_summary(line, sim_obs) for line in over
            ],
            "reconnects_lines": reconnects,
        }

    def _operator_override(self, action_id):
        for decision in self.blackboard.read().get("decisions", []):
            if decision.get("choice") == "override_veto" and decision.get("ref") in (
                action_id,
                None,
                "",
            ):
                return True
        return False

    def apply_action(self, action_id):
        act = self.registry.get(action_id)
        if act is None:
            return {
                "error": f"unknown action_id {action_id!r}; "
                "run search_topology_actions first"
            }
        if action_id not in self.asset_checked:
            return {
                "error": f"protocol: consult check_asset_health({action_id!r}) "
                "before applying"
            }
        if action_id not in self.screened:
            return {
                "error": f"protocol: consult screen_post_action({action_id!r}) "
                "before applying"
            }
        check = self.asset_checked[action_id]
        if check["verdict"] == "block" and not self._operator_override(action_id):
            return {
                "blocked": True,
                "by": "asset_health",
                "error": (
                    "Asset Health veto stands on this action; it can only be "
                    "cleared by an operator decision with choice "
                    "'override_veto' (sent as a structured decision from the "
                    "operator console). Offer the operator the options or "
                    "take a candidate at another substation."
                ),
                "reasons": check["reasons"],
            }
        with self.lock:
            self.obs, _, self.done, _ = self.env.step(act)
            self._baseline_screen = None
        if self.done:
            return {
                "applied": True,
                "game_over": True,
                "note": "grid collapsed after applying this action",
            }
        stable, worst_seen, steps = self._stability_check()
        result = {
            "applied": True,
            "max_rho": round(float(self.obs.rho.max()), 3),
            "n_overloaded": int((self.obs.rho > 1.0).sum()),
            "stable_steps_checked": steps,
            "stable": stable,
            "worst_rho_during_check": round(worst_seen, 3),
        }
        meta = self.meta.get(action_id)
        if meta:
            record = self.asset_health.record_switch(
                meta["substation"], meta["switching_ops"]
            )
            result["asset_wear"] = {
                "breaker": record["breaker"],
                "ops_used_month": record["ops_used_month"],
                "ops_remaining_month": record["ops_remaining_month"],
            }
        return result

    def check_asset_health(self, action_id):
        meta = self.meta.get(action_id)
        if meta is None:
            return {
                "error": f"unknown action_id {action_id!r}; "
                "run search_topology_actions first"
            }
        check = self.asset_health.check_action(
            meta["substation"], meta["switching_ops"]
        )
        check["action_id"] = action_id
        check["narration"] = asset_narrate(action_id, check)
        if check["verdict"] == "block":
            self.blackboard.append("vetoes", veto_item(action_id, check))
        self.asset_checked[action_id] = check
        return check

    def screen_post_action(self, action_id):
        act = self.registry.get(action_id)
        if act is None:
            return {
                "error": f"unknown action_id {action_id!r}; "
                "run search_topology_actions first"
            }
        result, self._baseline_screen = screen_post_action_env(
            self.env, self.obs, act, baseline_rows=self._baseline_screen
        )
        result["action_id"] = action_id
        self.screened[action_id] = result
        if action_id in self.meta:
            meta = self.meta[action_id]
            result["candidate"] = {
                "substation": meta["substation"],
                "description": meta["description"],
                "simulated_max_rho": meta["simulated_max_rho"],
            }
        self.blackboard.append("screening_verdicts", _screening_blackboard_item(result))
        return result

    def step_external(self, act):
        """Advance the REAL grid by one step from outside the operator loop
        (the EventInjector). Returns (done, obs). Resets the screening
        baseline because the live topology/timeseries has moved."""
        with self.lock:
            if self.done:
                return True, self.obs
            self.obs, _, self.done, _ = self.env.step(act)
            self._baseline_screen = None
            return self.done, self.obs

    def _stability_check(self):
        with self.lock:
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
            "check_asset_health",
            "screen_post_action",
            "apply_action",
        ):
            return json.dumps({"error": f"unknown tool {name!r}"})
        try:
            result = getattr(self, name)(**arguments)
        except TypeError as exc:
            result = {"error": f"bad arguments for {name}: {exc}"}
        except Exception as exc:
            result = {"error": f"{name} failed: {type(exc).__name__}: {exc}"}
        out = json.dumps(result, separators=(",", ":"))
        if len(out) > config.MAX_TOOL_RESULT_CHARS:
            preview = out[: config.MAX_TOOL_RESULT_CHARS - 100]
            out = json.dumps({"truncated": True, "preview": preview}, separators=(",", ":"))
        return out


def _screening_blackboard_item(result):
    worst = result.get("worst_next_contingency") or {}
    return {
        "from": "screening",
        "kind": "post_action_n1",
        "action_id": result.get("action_id"),
        "n1_secure": result.get("n1_secure"),
        "n1_not_worse": result.get("n1_not_worse"),
        "post_action_rho": result.get("post_action_rho"),
        "worst_next_contingency": {
            "line_id": worst.get("line_id"),
            "post_trip_rho": worst.get("post_trip_rho"),
            "diverged": worst.get("diverged"),
        },
        "screened_outages": result.get("screened_outages"),
        "insecure_outages": result.get("insecure_outages"),
        "reason": result.get("baseline_comparison"),
    }


def _compact_blackboard(board):
    latest_screening = None
    if board["screening_verdicts"]:
        latest = board["screening_verdicts"][-1]
        latest_screening = {
            "action_id": latest.get("action_id"),
            "n1_secure": latest.get("n1_secure"),
            "n1_not_worse": latest.get("n1_not_worse"),
            "post_action_rho": latest.get("post_action_rho"),
            "worst_next_contingency": latest.get("worst_next_contingency"),
            "insecure_outages": latest.get("insecure_outages"),
        }
    return {
        "constraints": [
            {
                "from": item.get("from"),
                "kind": item.get("kind"),
                "line_id": item.get("line_id"),
                "sub": item.get("sub"),
                "pct": item.get("pct"),
                "reason": (item.get("reason") or "")[:120],
            }
            for item in board["constraints"][-5:]
        ],
        "vetoes": [
            {
                "from": item.get("from"),
                "action_id": item.get("action_id"),
                "level": item.get("level"),
                "override": item.get("override"),
                "substation": item.get("substation"),
                "reason": (item.get("reason") or "")[:120],
            }
            for item in board["vetoes"][-3:]
        ],
        "latest_screening_verdict": latest_screening,
        "availability": board["availability"],
        "clock": board["clock"],
    }


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
            "name": "check_asset_health",
            "description": (
                "Ask the Asset Health advisor whether a candidate action is "
                "authorized given equipment condition (partial-discharge "
                "flags, breaker switching-cycle budget). Returns verdict "
                "ok | warn | block. A block requires an operator decision "
                "to override. Use before apply_action."
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
            "name": "screen_post_action",
            "description": (
                "Ask the Screening advisor to run N-1 screening on the "
                "POST-action topology for a candidate action. Use after "
                "simulate_action and before apply_action. Returns whether "
                "the fix is N-1 secure and the worst next contingency."
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
                "the next steps. Protocol-enforced: requires prior "
                "check_asset_health and screen_post_action for this "
                "action_id; an asset-health block requires an operator "
                "override_veto decision."
            ),
            "parameters": {
                "type": "object",
                "properties": {"action_id": {"type": "string"}},
                "required": ["action_id"],
            },
        },
    },
]
