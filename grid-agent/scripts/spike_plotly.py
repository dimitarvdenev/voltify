"""Render the three rescue-arc stages as interactive plotly HTML fragments.

Each stage becomes artifacts/stage_N.html (hover lines for loading %, zoom/pan).
artifacts/workflow.html embeds them via <iframe>.

Run: .venv/bin/python scripts/spike_plotly.py
"""

import grid2op
import numpy as np
from grid2op.PlotGrid import PlotPlotly


def save(fig, path):
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
    fig.write_html(path, include_plotlyjs="cdn", full_html=True)
    print("saved", path)


def main():
    env = grid2op.make("l2rpn_case14_sandbox", test=True)
    plot_helper = PlotPlotly(env.observation_space)

    obs = env.reset()
    save(plot_helper.plot_obs(obs), "artifacts/stage_1_healthy.html")

    worst = int(np.argmax(obs.rho))
    obs, _, _, _ = env.step(env.action_space({"set_line_status": [(worst, -1)]}))
    save(plot_helper.plot_obs(obs), "artifacts/stage_2_overloaded.html")

    best_rho, best_act = float(obs.rho.max()), None
    for sub_id in range(env.n_sub):
        for act in env.action_space.get_all_unitary_topologies_set(env.action_space, sub_id=sub_id):
            sim_obs, _, sim_done, _ = obs.simulate(act)
            if not sim_done and float(sim_obs.rho.max()) < best_rho:
                best_rho, best_act = float(sim_obs.rho.max()), act

    obs, _, _, _ = env.step(best_act)
    save(plot_helper.plot_obs(obs), "artifacts/stage_3_rescued.html")


if __name__ == "__main__":
    main()
