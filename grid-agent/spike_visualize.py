"""Render the rescue arc as PNGs: healthy -> overloaded -> rescued."""

import grid2op
import numpy as np
from grid2op.PlotGrid import PlotMatplot


def main():
    env = grid2op.make("l2rpn_case14_sandbox", test=True)
    plot_helper = PlotMatplot(env.observation_space)
    obs = env.reset()

    fig = plot_helper.plot_obs(obs)
    fig.savefig("artifacts/01_healthy.png", dpi=100)
    print("saved artifacts/01_healthy.png (rho max %.3f)" % obs.rho.max())

    worst = int(np.argmax(obs.rho))
    obs, _, _, _ = env.step(env.action_space({"set_line_status": [(worst, -1)]}))
    fig = plot_helper.plot_obs(obs)
    fig.savefig("artifacts/02_overloaded.png", dpi=100)
    print("saved artifacts/02_overloaded.png (rho max %.3f, overloads %d)"
          % (obs.rho.max(), (obs.rho > 1).sum()))

    best_rho, best_act = float(obs.rho.max()), None
    for sub_id in range(env.n_sub):
        for act in env.action_space.get_all_unitary_topologies_set(env.action_space, sub_id=sub_id):
            sim_obs, _, sim_done, _ = obs.simulate(act)
            if not sim_done and float(sim_obs.rho.max()) < best_rho:
                best_rho, best_act = float(sim_obs.rho.max()), act

    obs, _, _, _ = env.step(best_act)
    fig = plot_helper.plot_obs(obs)
    fig.savefig("artifacts/03_rescued.png", dpi=100)
    print("saved artifacts/03_rescued.png (rho max %.3f, overloads %d)"
          % (obs.rho.max(), (obs.rho > 1).sum()))


if __name__ == "__main__":
    main()
