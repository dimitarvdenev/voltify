"""Asset Health advisor.

Owns equipment condition: partial-discharge flags, breaker switching-cycle
budgets, cumulative wear across incidents. Authority: can veto an action
the Ops agent wants; a block routes to the operator for sign-off.
Backend: scenarios/assets.json (stand-in register, swap for CMMS export).
"""

import json
import os

from agent import config
from agent.advisors.voice import advisor_voice


BACKEND_PATH = os.path.join(config.ROOT, "scenarios", "assets.json")

SYSTEM_PROMPT = """\
You are the Asset Health advisor in a transmission control room. You own
equipment condition: breaker switching-cycle budgets, partial-discharge
flags, inspection findings. You can veto a switching action; a veto is
not a refusal to help - name the options that remain (operator sign-off,
a different substation, an inspection crew). Speak briefly, like an
engineer protecting equipment.
"""


class AssetHealth:
    def __init__(self, path=BACKEND_PATH):
        with open(path) as f:
            self.backend = json.load(f)
        # per-run wear on top of the monthly counts in the register;
        # this is the cross-incident memory the Ops agent does not have
        self.run_ops = {}

    def record_for(self, substation):
        record = dict(self.backend["default"])
        record.update(self.backend["breakers"].get(str(int(substation)), {}))
        record.setdefault("breaker", f"B-{int(substation):03d}")
        record["ops_used_month"] = (
            record["ops_used_month"] + self.run_ops.get(int(substation), 0)
        )
        record["ops_remaining_month"] = (
            record["ops_budget_month"] - record["ops_used_month"]
        )
        return record

    def check_action(self, substation, switching_ops):
        """Deterministic verdict: ok | warn | block."""
        record = self.record_for(substation)
        policy = self.backend["policy"]
        verdict, reasons = "ok", []
        remaining_after = record["ops_remaining_month"] - int(switching_ops)
        if record["pd_flag"]:
            verdict = "block"
            reasons.append(
                f"{record['breaker']}: {record.get('pd_note', 'partial-discharge flag')}; "
                + policy["pd_block_note"]
            )
        if remaining_after < 0:
            verdict = "block"
            reasons.append(
                f"{record['breaker']}: switching budget exhausted "
                f"({record['ops_remaining_month']} ops left this month, "
                f"action needs {int(switching_ops)})"
            )
        elif remaining_after < policy["warn_margin_ops"] and verdict == "ok":
            verdict = "warn"
            reasons.append(
                f"{record['breaker']}: only {record['ops_remaining_month']} switching "
                f"ops left this month; this action uses {int(switching_ops)}"
            )
        result = {
            "substation": int(substation),
            "verdict": verdict,
            "override": "human" if verdict == "block" else None,
            "reasons": reasons,
            "cycle_budget": {
                "breaker": record["breaker"],
                "ops_used_month": record["ops_used_month"],
                "ops_budget_month": record["ops_budget_month"],
                "ops_remaining_month": record["ops_remaining_month"],
            },
            "last_inspection": record["last_inspection"],
        }
        if record.get("inspection_dispatch_minutes"):
            result["inspection_dispatch_minutes"] = record[
                "inspection_dispatch_minutes"
            ]
        return result

    def record_switch(self, substation, switching_ops):
        """Cumulative wear memory: called on every real apply."""
        sub = int(substation)
        self.run_ops[sub] = self.run_ops.get(sub, 0) + int(switching_ops)
        return self.record_for(sub)


def veto_item(action_id, check):
    return {
        "from": "asset_health",
        "kind": "veto",
        "action_id": action_id,
        "level": check["verdict"],
        "override": check["override"],
        "substation": check["substation"],
        "reason": "; ".join(check["reasons"]),
    }


def narrate(action_id, check, client=None):
    budget = check["cycle_budget"]
    if check["verdict"] == "ok":
        fallback = (
            f"Asset Health: no objection to {action_id}. "
            f"{budget['breaker']} is clean, "
            f"{budget['ops_remaining_month']} of {budget['ops_budget_month']} "
            f"switching ops left this month."
        )
    elif check["verdict"] == "warn":
        fallback = (
            f"Asset Health: caution on {action_id}. " + "; ".join(check["reasons"])
            + ". Electrically your call, but spread the load if an "
            "alternative exists."
        )
    else:
        options = (
            "Options: (a) operator signs off and accepts the asset risk, "
            "(b) take a candidate at another substation"
        )
        if check.get("inspection_dispatch_minutes"):
            options += (
                f", (c) dispatch an inspection crew first "
                f"(~{check['inspection_dispatch_minutes']} min)"
            )
        fallback = (
            f"Asset Health: I cannot authorize {action_id}. "
            + "; ".join(check["reasons"])
            + f". {options}."
        )
    facts = dict(check, action_id=action_id)
    return advisor_voice(client, SYSTEM_PROMPT, facts, fallback)
