"""Classify all single-line N-1 outages relative to the stressed baseline."""

import json
import os
import time

from agent import config
from agent.tools import GridTools

RHO_DELTA = 0.05


def main():
    tools = GridTools()
    obs, env = tools.obs, tools.env
    base_max = float(obs.rho.max())
    base_over = int((obs.rho > 1.0).sum())
    rows, t0 = [], time.time()
    for line_id in range(env.n_line):
        if not obs.line_status[line_id]:
            continue
        act = env.action_space({"set_line_status": [(int(line_id), -1)]})
        sim_obs, _, sim_done, _ = obs.simulate(act)
        if sim_done:
            verdict, worst, n_over = "dangerous-diverged", None, None
        else:
            worst = float(sim_obs.rho.max())
            n_over = int((sim_obs.rho > 1.0).sum())
            worse = (worst - base_max) > RHO_DELTA or n_over > base_over
            verdict = "dangerous" if worse else "harmless-vs-baseline"
        rows.append(
            {
                "line_id": int(line_id),
                "from_sub": int(obs.line_or_to_subid[line_id]),
                "to_sub": int(obs.line_ex_to_subid[line_id]),
                "max_rho_after": worst,
                "n_overloaded_after": n_over,
                "verdict": verdict,
            }
        )
    elapsed = round(time.time() - t0, 1)
    summary = {
        "baseline_max_rho": base_max,
        "baseline_n_overloaded": base_over,
        "n_screened": len(rows),
        "screening_seconds": elapsed,
        "n_dangerous": sum(row["verdict"].startswith("dangerous") for row in rows),
        "n_diverged": sum(row["verdict"] == "dangerous-diverged" for row in rows),
        "rho_delta_threshold": RHO_DELTA,
        "outages": rows,
    }
    out_json = os.path.join(config.ROOT, "artifacts", "screening_118.json")
    with open(out_json, "w") as f:
        json.dump(summary, f, indent=2)

    dangerous = [row for row in rows if row["verdict"].startswith("dangerous")]
    dangerous.sort(key=lambda row: -(row["max_rho_after"] or 99))
    lines = [
        f"# N-1 screening - 118-bus grid, stressed baseline (max rho {base_max:.2f})",
        "",
        (
            f"{len(rows)} outages screened in {elapsed}s - "
            f"{summary['n_dangerous']} dangerous "
            f"({summary['n_diverged']} diverged), "
            f"{len(rows) - summary['n_dangerous']} harmless vs baseline."
        ),
        "",
        "| line | subs | max rho after | verdict |",
        "|---|---|---|---|",
    ]
    for row in dangerous[:20]:
        rho_txt = "diverged" if row["max_rho_after"] is None else f"{row['max_rho_after']:.2f}"
        lines.append(
            f"| {row['line_id']} | {row['from_sub']}->{row['to_sub']} "
            f"| {rho_txt} | {row['verdict']} |"
        )
    out_md = os.path.join(config.ROOT, "artifacts", "screening_118.md")
    with open(out_md, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(
        f"screened {len(rows)} in {elapsed}s -> "
        f"{summary['n_dangerous']} dangerous. Wrote {out_json}, {out_md}"
    )


if __name__ == "__main__":
    main()
