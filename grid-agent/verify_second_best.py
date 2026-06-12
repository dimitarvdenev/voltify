"""Verify the constraint-twist rescue with substation 67 excluded."""

import json
import os

from agent import config
from agent.tools import GridTools

with open(os.path.join(config.ROOT, "scenarios", "arc_118.json")) as f:
    ARC = json.load(f)


def main():
    tools = GridTools()
    res = tools.search_topology_actions(
        ARC["scoped_subs"],
        exclude_substations=[ARC["rescue_substation"]],
    )
    if not res["candidates"]:
        print(
            "NO-GO: no candidates with sub 67 excluded. "
            "Try widening: tools._scoped_subs(n_hops=2)"
        )
        return
    best = res["candidates"][0]
    print("best without sub 67:", json.dumps(best, indent=2))
    if best["simulated_max_rho"] >= 1.0:
        print(
            "NO-GO: second-best does not rescue (rho >= 1.0). "
            "Constraint-twist beat needs a different exclusion - "
            "try excluding a non-critical scoped sub instead."
        )
        return
    out = tools.apply_action(best["action_id"])
    print("applied:", json.dumps(out, indent=2))
    record = {
        "excluded_substation": ARC["rescue_substation"],
        "second_best": best,
        "applied": out,
        "verified_from": "verify_second_best.py",
    }
    path = os.path.join(config.ROOT, "scenarios", "second_best_118.json")
    with open(path, "w") as f:
        json.dump(record, f, indent=2)
    print("GO - saved", path)


if __name__ == "__main__":
    main()
