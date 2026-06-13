"""Tool layer: Grid2Op env plus server-side action registry."""

import json
import os
import threading

import grid2op
import numpy as np

from agent import config
from agent.action_search import (
    action_effects,
    search_curtailment,
    search_redispatch,
    search_topology,
)
from agent.advisors.asset_health import AssetHealth, narrate as asset_narrate, veto_item
from agent.advisors.blackboard import Blackboard
from agent.advisors.screening import screen_post_action_env
from agent.grid_summary import (
    label_substation,
    line_summary,
    scoped_substations,
    summarize_grid_state,
)
from agent.tool_blackboard import screening_blackboard_item
from agent.tool_schema import TOOLS_SCHEMA as TOOLS_SCHEMA


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

    def _substation_label(self, sub_id, obs=None):
        return label_substation(self.env, obs or self.obs, sub_id)

    def _line_summary(self, line_id, obs=None):
        return line_summary(self.env, obs or self.obs, line_id)

    def _scoped_subs(self, n_hops=1):
        return scoped_substations(self.env, self.obs, n_hops=n_hops)

    def get_grid_state(self):
        return summarize_grid_state(self.env, self.obs, self.blackboard.read())

    def _register_search_result(self, result):
        self.registry.update(result.actions)
        self.meta.update(result.meta)
        return result.payload

    def search_topology_actions(self, substations, exclude_substations=None):
        return self._register_search_result(
            search_topology(self.env, self.obs, substations, exclude_substations)
        )

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
        reconnects, _ = action_effects(self.env, self.obs, act, sim_obs)
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

    def search_redispatch_actions(self, max_candidates=None):
        return self._register_search_result(
            search_redispatch(self.env, self.obs, max_candidates)
        )

    def search_curtailment_actions(self, max_candidates=None):
        return self._register_search_result(
            search_curtailment(self.env, self.obs, max_candidates)
        )

    def _operator_override(self, action_id):
        for decision in self.blackboard.read().get("decisions", []):
            if (
                decision.get("choice") == "override_veto"
                and decision.get("ref") == action_id
            ):
                return True
        return False

    def apply_action(self, action_id):
        act, error = self._validated_action(action_id)
        if error is not None:
            return error
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
        self._add_action_side_effects(result, action_id)
        return result

    def _validated_action(self, action_id):
        act = self.registry.get(action_id)
        if act is None:
            return None, {
                "error": f"unknown action_id {action_id!r}; "
                "run search_topology_actions first"
            }
        if action_id not in self.asset_checked:
            return None, {
                "error": f"protocol: consult check_asset_health({action_id!r}) "
                "before applying"
            }
        if action_id not in self.screened:
            return None, {
                "error": f"protocol: consult screen_post_action({action_id!r}) "
                "before applying"
            }
        check = self.asset_checked[action_id]
        if check["verdict"] == "block" and not self._operator_override(action_id):
            return None, self._asset_block_response(check)
        return act, None

    def _asset_block_response(self, check):
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

    def _add_action_side_effects(self, result, action_id):
        meta = self.meta.get(action_id)
        if meta and meta.get("kind") == "topology":
            record = self.asset_health.record_switch(
                meta["substation"], meta["switching_ops"]
            )
            result["asset_wear"] = {
                "breaker": record["breaker"],
                "ops_used_month": record["ops_used_month"],
                "ops_remaining_month": record["ops_remaining_month"],
            }
        elif meta and meta.get("kind") in ("redispatch", "curtail"):
            result["cost_class"] = meta.get("cost_class")
            result["mw_shifted"] = meta.get("mw_shifted")

    def check_asset_health(self, action_id):
        meta = self.meta.get(action_id)
        if meta is None:
            return {
                "error": f"unknown action_id {action_id!r}; "
                "run search_topology_actions first"
            }
        if meta.get("kind") != "topology":
            # Redispatch/curtailment switch no breakers - equipment condition
            # is not a constraint, so Asset Health has no veto here.
            check = {
                "action_id": action_id,
                "verdict": "ok",
                "override": None,
                "reasons": [],
                "asset_note": (
                    f"{meta.get('kind')} action: no breaker switching, "
                    "Asset Health has no objection"
                ),
            }
            self.asset_checked[action_id] = check
            return check
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
        # MultiMixEnv.copy() temporarily nulls self.env.current_env on the
        # shared env (grid2op multiMixEnv ~L522) and restores it afterward.
        # That null window races the injector thread's env access and crashes
        # with "'NoneType' has no attribute action_space". Serialize the copy
        # under the same lock the injector and env-step paths use.
        with self.lock:
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
        self.blackboard.append("screening_verdicts", screening_blackboard_item(result))
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
            "search_redispatch_actions",
            "search_curtailment_actions",
            "simulate_action",
            "check_asset_health",
            "screen_post_action",
            "apply_action",
        ):
            return json.dumps({"error": f"unknown tool {name!r}"})
        try:
            # Serialize every tool call against the injector thread. Operator
            # tools touch the shared grid2op backend (obs.simulate, env.copy,
            # env.step); the injector does too. Without this the two threads
            # race the MultiMixEnv and crash on a transiently-null current_env.
            # RLock is reentrant, so inner `with self.lock` blocks stay valid.
            with self.lock:
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
