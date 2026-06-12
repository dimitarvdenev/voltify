"""Scale the case14 grid loads by a real ENTSO-E load curve and render it.

Story: instead of a synthetic/random snapshot, the demo grid's load level
reflects an actual moment from Germany's grid (ENTSO-E load curve), so the
"is the grid stressed right now" framing is grounded in real data.

Run: .venv/bin/python spike_real_load_network.py
"""

import re
import grid2op
import numpy as np
from grid2op.PlotGrid import PlotMatplot


def load_entsoe_series(path):
    xml = open(path).read()
    quantities = [float(q) for q in re.findall(r"<quantity>([\d.]+)</quantity>", xml)]
    return np.array(quantities)


def main():
    load_mw = load_entsoe_series("data/entsoe_de_load_raw.xml")
    print(f"loaded {len(load_mw)} points from ENTSO-E (DE, today)")
    print(f"min {load_mw.min():.0f} MW, max {load_mw.max():.0f} MW, mean {load_mw.mean():.0f} MW")

    # scale factor: how loaded is the *current* real grid vs. its own daily average
    # this is the number we use to scale the toy grid's load
    peak_idx = int(np.argmax(load_mw))
    scale = load_mw[peak_idx] / load_mw.mean()
    print(f"peak/mean ratio = {scale:.3f} (peak at slot {peak_idx})")

    env = grid2op.make("l2rpn_case14_sandbox", test=True)
    obs = env.reset()
    print(f"\ncase14 baseline: max rho = {obs.rho.max():.3f}")

    # scale all loads by the real-data peak/mean ratio
    load_p = obs.load_p * scale
    act = env.action_space({"injection": {"load_p": load_p}})
    obs2, _, done, info = obs.simulate(act)
    print(f"case14 scaled to real DE peak/mean ratio ({scale:.3f}x): "
          f"max rho = {obs2.rho.max():.3f}, overloads = {int((obs2.rho > 1).sum())}, done = {done}")

    plot_helper = PlotMatplot(env.observation_space)
    fig = plot_helper.plot_obs(obs2)
    fig.savefig("artifacts/04_real_load_scaled.png", dpi=100)
    print("saved artifacts/04_real_load_scaled.png")


if __name__ == "__main__":
    main()
