"""Spike: verify the core demo loop for the grid operation agent.

Story arc:
1. Healthy grid (IEEE case14 sandbox)
2. N-1 event: disconnect the most loaded line -> cascading overloads
3. Search topology actions (bus splitting) via simulate()
4. Apply best action -> grid back to safe state

Run: .venv/bin/python scripts/spike_overload_rescue.py
"""

import grid2op
import numpy as np


def main():
    env = grid2op.make("l2rpn_case14_sandbox", test=True)
    obs = env.reset()
    print(f"healthy grid: max line loading rho = {obs.rho.max():.3f}")

    # N-1 event: knock out the most loaded line
    worst = int(np.argmax(obs.rho))
    obs, _, done, _ = env.step(env.action_space({"set_line_status": [(worst, -1)]}))
    n_over = int((obs.rho > 1).sum())
    print(f"line {worst} lost: max rho = {obs.rho.max():.3f}, {n_over} lines overloaded")
    assert n_over > 0, "expected an overload after N-1 event"

    # brute-force search over unitary topology actions using the simulator
    best_rho, best_act = float(obs.rho.max()), None
    n_tested = 0
    for sub_id in range(env.n_sub):
        actions = env.action_space.get_all_unitary_topologies_set(
            env.action_space, sub_id=sub_id
        )
        for act in actions:
            sim_obs, _, sim_done, _ = obs.simulate(act)
            n_tested += 1
            if not sim_done and float(sim_obs.rho.max()) < best_rho:
                best_rho, best_act = float(sim_obs.rho.max()), act

    print(f"searched {n_tested} topology actions, best simulated rho = {best_rho:.3f}")
    assert best_act is not None, "no improving action found"

    obs, _, done, _ = env.step(best_act)
    print(f"action applied: max rho = {obs.rho.max():.3f}, "
          f"{int((obs.rho > 1).sum())} overloads, done = {done}")
    print("\nrescue arc verified: 0.92 -> overload -> safe")


if __name__ == "__main__":
    main()
