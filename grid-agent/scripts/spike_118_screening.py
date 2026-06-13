"""Re-spike on 118-bus env: N-1 screening timing + action-space size.

Answers (per PRD open items):
- how long does one power flow take
- how long does screening all 186 N-1 outages take, how many are dangerous
- how big is the unitary topology action space (total + per-substation)
"""
import time

import grid2op
import numpy as np

grid2op.change_local_dir("/Users/dimitardenev/Projects/voltify/spike/grid-agent/data_grid2op")

t0 = time.time()
env = grid2op.make("l2rpn_neurips_2020_track2_small")
obs = env.reset()
print(f"env ready in {time.time() - t0:.1f}s")
print(f"start state: max rho {obs.rho.max():.3f}, "
      f"{int((obs.rho > 1.0).sum())} lines overloaded, "
      f"{int((~obs.line_status).sum())} lines already off")

# single power-flow cost via simulate(do-nothing)
do_nothing = env.action_space({})
t0 = time.time()
for _ in range(10):
    obs.simulate(do_nothing)
per_solve = (time.time() - t0) / 10
print(f"single simulate: {per_solve * 1000:.0f} ms")

# N-1 screening: disconnect each line, simulate, record worst rho
t0 = time.time()
results = []
for line_id in range(env.n_line):
    if not obs.line_status[line_id]:
        continue
    act = env.action_space({"set_line_status": [(line_id, -1)]})
    sim_obs, _, sim_done, _ = obs.simulate(act)
    worst = sim_obs.rho.max() if not sim_done else np.inf
    results.append((line_id, worst, sim_done))
elapsed = time.time() - t0
dangerous = [(l, r, d) for l, r, d in results if r > 1.0 or d]
diverged = [l for l, r, d in results if d]
print(f"\nN-1 screening: {len(results)} outages in {elapsed:.1f}s "
      f"({elapsed / len(results) * 1000:.0f} ms each)")
print(f"dangerous (rho>1 or diverged): {len(dangerous)} / {len(results)}, "
      f"of which diverged: {len(diverged)}")
top = sorted((x for x in dangerous if not x[2]), key=lambda x: -x[1])[:10]
for line_id, worst, _ in top:
    print(f"  line {line_id:3d} "
          f"({obs.line_or_to_subid[line_id]}->{obs.line_ex_to_subid[line_id]}): "
          f"max rho {worst:.2f}")

# action-space size: total unitary bus-splits, and per-sub near worst overload
t0 = time.time()
per_sub = []
for sub_id in range(env.n_sub):
    acts = env.action_space.get_all_unitary_topologies_set(env.action_space, sub_id=sub_id)
    per_sub.append(len(acts))
total = sum(per_sub)
print(f"\nunitary topology actions: {total} total "
      f"(counted in {time.time() - t0:.1f}s)")
print(f"biggest substations: "
      f"{sorted(enumerate(per_sub), key=lambda x: -x[1])[:5]}")

# scoped search cost estimate: subs touching the worst overloaded line
if top:
    worst_line = top[0][0]
    subs = {int(obs.line_or_to_subid[worst_line]), int(obs.line_ex_to_subid[worst_line])}
    scoped = sum(per_sub[s] for s in subs)
    print(f"\nscoped search around line {worst_line} (subs {subs}): "
          f"{scoped} actions ≈ {scoped * per_solve:.0f}s simulate time")
