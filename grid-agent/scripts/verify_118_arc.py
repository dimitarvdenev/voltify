"""Keystone verification for the 118-bus pivot (PRD open item #1).

Proves (or refutes) the full demo arc on l2rpn_neurips_2020_track2_small:
healthy snapshot -> N-1 outage creates overload -> a scoped topology
(bus-split) action rescues the grid (max rho < 1.0).

Output: GO/NO-GO verdict + scenarios/arc_118.json describing the proven arc.
"""
import json
import os
import time

import grid2op
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
grid2op.change_local_dir(os.path.join(HERE, "data_grid2op"))

HEALTHY_RHO = 0.95          # snapshot counts as healthy below this
MAX_ACTIONS_PER_SUB = 600   # skip monster substations (sub 48 has 65k combos)
MAX_CHRONICS_TO_SCAN = 20
MAX_OUTAGES_TO_TRY = 8      # dangerous outages tried per snapshot


def find_healthy_snapshots(env):
    """Yield (chronic_idx, obs) whose starting state is healthy."""
    for idx in range(MAX_CHRONICS_TO_SCAN):
        env.set_id(idx)
        obs = env.reset()
        print(f"chronic {idx}: start max rho {obs.rho.max():.3f}")
        if obs.rho.max() < HEALTHY_RHO:
            yield idx, obs


def screen_outages(env, obs):
    """N-1 screening relative to baseline. Returns dangerous outages,
    worst first: (line_id, max_rho, diverged)."""
    dangerous = []
    for line_id in range(env.n_line):
        if not obs.line_status[line_id]:
            continue
        act = env.action_space({"set_line_status": [(line_id, -1)]})
        sim_obs, _, sim_done, _ = obs.simulate(act)
        if sim_done:
            dangerous.append((line_id, np.inf, True))
        elif sim_obs.rho.max() > 1.0:
            dangerous.append((line_id, float(sim_obs.rho.max()), False))
    dangerous.sort(key=lambda x: -x[1] if np.isfinite(x[1]) else 0)
    # non-diverged first (diverged cases need more than one action; skip
    # for the demo arc), worst overload first
    finite = [d for d in dangerous if not d[2]]
    return finite + [d for d in dangerous if d[2]]


def scoped_substations(obs_after, n_hops):
    """Substations at the endpoints of overloaded lines, optionally grown
    by one line-hop."""
    over = np.where(obs_after.rho > 1.0)[0]
    subs = set()
    for line_id in over:
        subs.add(int(obs_after.line_or_to_subid[line_id]))
        subs.add(int(obs_after.line_ex_to_subid[line_id]))
    for _ in range(n_hops):
        grown = set(subs)
        for line_id in range(len(obs_after.rho)):
            a = int(obs_after.line_or_to_subid[line_id])
            b = int(obs_after.line_ex_to_subid[line_id])
            if a in subs:
                grown.add(b)
            if b in subs:
                grown.add(a)
        subs = grown
    return sorted(subs)


def best_topology_rescue(env, obs_after, subs):
    """Simulate every unitary bus-split at the scoped substations.
    Returns (best_rho, sub_id, action, n_tried, seconds)."""
    t0 = time.time()
    best = (np.inf, None, None)
    n_tried = 0
    for sub_id in subs:
        acts = env.action_space.get_all_unitary_topologies_set(
            env.action_space, sub_id=sub_id)
        if len(acts) > MAX_ACTIONS_PER_SUB:
            print(f"    sub {sub_id}: {len(acts)} actions — skipped (cap)")
            continue
        for act in acts:
            sim_obs, _, sim_done, _ = obs_after.simulate(act)
            n_tried += 1
            if sim_done:
                continue
            worst = float(sim_obs.rho.max())
            if worst < best[0]:
                best = (worst, sub_id, act)
    return *best, n_tried, time.time() - t0


def main():
    env = grid2op.make("l2rpn_neurips_2020_track2_small")

    for chronic_idx, obs in find_healthy_snapshots(env):
        base_rho = float(obs.rho.max())
        dangerous = screen_outages(env, obs)
        print(f"  chronic {chronic_idx}: {len(dangerous)} dangerous outages")
        if not dangerous:
            continue

        for line_id, outage_rho, diverged in dangerous[:MAX_OUTAGES_TO_TRY]:
            if diverged:
                continue
            # re-enter the snapshot fresh, then let the outage actually happen
            env.set_id(chronic_idx)
            env.reset()
            outage = env.action_space({"set_line_status": [(line_id, -1)]})
            obs_after, _, done, _ = env.step(outage)
            if done or obs_after.rho.max() <= 1.0:
                continue
            print(f"\n  outage line {line_id} "
                  f"({obs_after.line_or_to_subid[line_id]}->"
                  f"{obs_after.line_ex_to_subid[line_id]}): "
                  f"max rho {obs_after.rho.max():.2f}, "
                  f"{int((obs_after.rho > 1.0).sum())} lines overloaded")

            for n_hops in (0, 1):
                subs = scoped_substations(obs_after, n_hops)
                rho, sub_id, act, n_tried, secs = best_topology_rescue(
                    env, obs_after, subs)
                print(f"    scope hops={n_hops} ({len(subs)} subs, "
                      f"{n_tried} actions, {secs:.1f}s): best rho {rho:.3f}"
                      + (f" via bus-split at sub {sub_id}" if sub_id is not None else ""))
                if rho < 1.0:
                    result = {
                        "env": "l2rpn_neurips_2020_track2_small",
                        "chronic_idx": chronic_idx,
                        "healthy_max_rho": base_rho,
                        "outage_line_id": int(line_id),
                        "overloaded_max_rho": float(obs_after.rho.max()),
                        "n_overloaded": int((obs_after.rho > 1.0).sum()),
                        "rescue_substation": int(sub_id),
                        "rescued_max_rho": rho,
                        "scope_hops": n_hops,
                        "scoped_subs": subs,
                        "actions_simulated": n_tried,
                        "search_seconds": round(secs, 1),
                    }
                    os.makedirs(os.path.join(HERE, "scenarios"), exist_ok=True)
                    out = os.path.join(HERE, "scenarios", "arc_118.json")
                    with open(out, "w") as f:
                        json.dump(result, f, indent=2)
                    print("\nGO — full arc proven on 118 buses:")
                    print(json.dumps(result, indent=2))
                    return

    print("\nNO-GO — no single bus-split rescue found in scanned scenarios. "
          "Fallback per PRD: case14 demo, 118 as benchmark slide.")


if __name__ == "__main__":
    main()
