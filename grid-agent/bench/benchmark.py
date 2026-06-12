"""Agent vs scoped brute-force vs do-nothing benchmark table."""

import argparse
import json
import os
import time

from agent import config
from agent.llm import make_client, run_loop
from agent.prompts import SCENARIO_BRIEF, SYSTEM_PROMPT
from agent.tools import TOOLS_SCHEMA, GridTools

BLIND_BRUTE_FORCE_NOTE = "72107 actions x ~32 ms = ~38 min (quoted, not run)"


def load_scenarios(limit):
    path = os.path.join(config.ROOT, "artifacts", "screening_118.json")
    with open(path) as f:
        screening = json.load(f)
    worst = [
        row for row in screening["outages"] if row["verdict"] == "dangerous"
    ]
    worst.sort(key=lambda row: -(row["max_rho_after"] or 0))
    return [None] + [row["line_id"] for row in worst[: limit - 1]]


def setup(outage_line):
    tools = GridTools()
    if outage_line is not None:
        act = tools.env.action_space(
            {"set_line_status": [(int(outage_line), -1)]}
        )
        tools.obs, _, tools.done, _ = tools.env.step(act)
    return tools


def run_do_nothing(outage_line):
    tools = setup(outage_line)
    if tools.done:
        return {"rescued": False, "note": "game over at outage"}
    stable, worst, steps = tools._stability_check()
    return {
        "rescued": bool(stable and worst < 1.0),
        "survived_steps": steps,
        "worst_rho": worst,
    }


def run_brute_force(outage_line):
    tools = setup(outage_line)
    if tools.done:
        return {"rescued": False, "note": "game over at outage"}
    t0 = time.time()
    scope = tools._scoped_subs(n_hops=1)
    res = tools.search_topology_actions(scope)
    if not res["candidates"]:
        return {"rescued": False, "wallclock_s": round(time.time() - t0, 1)}
    best = res["candidates"][0]
    applied = tools.apply_action(best["action_id"])
    return {
        "rescued": bool(applied.get("max_rho", 9) < 1.0),
        "actions_taken": 1,
        "actions_simulated": res["actions_simulated"],
        "wallclock_s": round(time.time() - t0, 1),
    }


def run_agent(outage_line):
    tools = setup(outage_line)
    if tools.done:
        return {"rescued": False, "note": "game over at outage"}
    client = make_client()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": SCENARIO_BRIEF
            + "\nOperator: check the grid and secure it if needed.",
        },
    ]
    applies = []
    t0 = time.time()

    def on_event(kind, payload):
        if kind == "tool" and payload["tool"] == "apply_action":
            applies.append(payload)

    run_loop(
        client,
        config.LLM_MODEL,
        messages,
        TOOLS_SCHEMA,
        tools.dispatch,
        on_event=on_event,
    )
    return {
        "rescued": bool(float(tools.obs.rho.max()) < 1.0 and not tools.done),
        "actions_taken": len(applies),
        "wallclock_s": round(time.time() - t0, 1),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-agent", action="store_true")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    results = []
    for outage in load_scenarios(args.limit):
        name = "crisis-at-open" if outage is None else f"outage-line-{outage}"
        print(f"== {name}")
        row = {
            "scenario": name,
            "do_nothing": run_do_nothing(outage),
            "scoped_brute_force": run_brute_force(outage),
        }
        if args.with_agent:
            row["agent"] = run_agent(outage)
        results.append(row)

    out = {"blind_brute_force": BLIND_BRUTE_FORCE_NOTE, "results": results}
    out_json = os.path.join(config.ROOT, "artifacts", "benchmark_118.json")
    with open(out_json, "w") as f:
        json.dump(out, f, indent=2)

    cols = ["do_nothing", "scoped_brute_force"] + (
        ["agent"] if args.with_agent else []
    )
    lines = [
        "# Benchmark - one-shot rescue per scenario",
        "",
        f"Blind brute force: {BLIND_BRUTE_FORCE_NOTE}",
        "",
        "| scenario | " + " | ".join(cols) + " |",
        "|" + "---|" * (len(cols) + 1),
    ]
    for row in results:
        cells = []
        for col in cols:
            data = row[col]
            mark = "rescued" if data.get("rescued") else "FAILED"
            extra = f" ({data['wallclock_s']}s)" if "wallclock_s" in data else ""
            cells.append(mark + extra)
        lines.append(f"| {row['scenario']} | " + " | ".join(cells) + " |")
    out_md = os.path.join(config.ROOT, "artifacts", "benchmark_118.md")
    with open(out_md, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("wrote", out_json, "and", out_md)


if __name__ == "__main__":
    main()
