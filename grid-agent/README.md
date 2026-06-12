# Grid Operation Agent (Challenge 5)

LLM agent that returns an overloaded power grid to a safe state while narrating
its reasoning. Built on Grid2Op (IEEE case14 sandbox to start).

## Spike result (verified)

The full demo arc works end to end:

| Step | Max line loading (rho) |
|------|------------------------|
| Healthy grid | 0.92 |
| N-1 event (lose most-loaded line) | 1.91 — 4 lines overloaded |
| Best topology action (bus split, found via simulate) | **0.83 — zero overloads** |

Redispatch alone is too weak for this case; topology actions are the lever.
178 unitary topology actions searched in seconds — fast enough for an
agent tool call.

## Setup

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python spike_overload_rescue.py
```

Note: system python3 is 3.9 (too old), homebrew is 3.14 (too new for wheels).
Use uv-managed 3.12.

## Architecture sketch

- **Env**: Grid2Op `l2rpn_case14_sandbox` (later: bigger L2RPN envs)
- **Agent tools** (engineer):
  - `get_grid_state` — loads, gens, line flows, rho per line
  - `simulate_action` — dry-run any action via `obs.simulate()`
  - `apply_action` — step the env
- **Agent loop**: Claude reasons over state, proposes candidate actions,
  simulates, applies best, narrates each step
- **Baseline** (for benchmark slide): brute-force topology search
  (already in spike) + do-nothing
- **Scenarios** (energy expert): pick dramatic-but-solvable overload cases,
  define safe-state metric
