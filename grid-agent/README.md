# Grid Operation Agent (Challenge 5)

LLM agent that returns an overloaded power grid to a safe state while narrating
its reasoning. Built on Grid2Op with a 118-bus demo scenario and a multi-agent
advisor ring (Weather, Asset Health, Screening, and a Grid Events injector).

📖 **Full documentation:** [`docs/DOCUMENTATION.md`](docs/DOCUMENTATION.md) —
install, demo walkthrough, stack, data/scenarios, conceptual approach, and the
software-engineering view (with diagrams).

## Project layout

```text
agent/       Runtime agent, tools, prompts, advisor backends, renderer
bench/       Benchmark and N-1 screening utilities
data/        Small checked-in data inputs (ENTSO-E load curve, 118-bus layout)
data_grid2op/ Local Grid2Op dataset (118-bus MultiMix environment)
docs/        Product/spec/planning/handoff documents + DOCUMENTATION.md
scenarios/   Scripted demo scenario data (assets, weather, arc, second-best)
scripts/     One-off spike and verification scripts
tests/       Pytest suite
ui/          Static demo UI and local server
artifacts/   Checked-in demo outputs, screenshots, and video
```

## Spike result (verified)

The full demo arc works end to end on the 118-bus grid
(`scenarios/arc_118.json`, "crisis-at-open"):

| Step | Max line loading (rho) |
|------|------------------------|
| Crisis at session open (line 177, subs 115↔67) | 1.30 |
| Do-nothing | grid blacks out after 4 steps |
| Best topology action (bus-split at sub 67, found via simulate) | **0.80 — zero overloads, stable 20 steps** |

Redispatch alone is too weak for this case; topology actions are the lever.
**88 of 72,107** unitary topology actions searched in ~3 s — fast enough for an
agent tool call (blind brute-force is ~38 min).

## Setup

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python scripts/spike_overload_rescue.py
```

Note: system python3 is 3.9 (too old), homebrew is 3.14 (too new for wheels).
Use uv-managed 3.12. The agent talks to an OpenAI-compatible endpoint (a local
MLX model server by default — see `agent/config.py`).

## Demo

From this directory, run:

```bash
make demo
```

Then open `http://localhost:8000/ui/index.html`. The Makefile starts the
static UI server and runs the agent in inbox mode (with the event injector) so
messages sent from the web input are consumed by the agent.

Useful separate targets:

```bash
make ui      # serve only the web UI
make agent   # run only the inbox agent
make test    # run the test suite
```

Drive the agent with plain operator messages, e.g.
`Shift start. Please check the grid and secure it if needed.` See
[`docs/DOCUMENTATION.md`](docs/DOCUMENTATION.md) §2 for the verified prompt set.

## Architecture sketch

- **Env**: Grid2Op `l2rpn_neurips_2020_track2_small` (118-bus MultiMix) over a
  PandaPower power-flow backend.
- **Agent tools** (8):
  - `get_grid_state` — loads, gens, line flows, rho per line, search scope
  - `search_topology_actions` — grounded candidate bus-split actions
  - `search_redispatch_actions` — escalation step 3 (expensive)
  - `search_curtailment_actions` — escalation step 4 (last resort)
  - `simulate_action` — dry-run a registered candidate action
  - `check_asset_health` — Asset Health veto/warn/ok
  - `screen_post_action` — Screening post-action N-1 verdict
  - `apply_action` — step the real env (protocol-gated)
- **Advisor ring**: Weather (thermal derates), Asset Health (breaker/condition
  veto), Screening (post-action N-1), Grid Events injector (autonomous world
  dynamics) — coordinated over a file-backed blackboard.
- **Agent loop**: a local OpenAI-compatible model reasons over tool results,
  simulates candidates, consults advisors, applies only authorized actions
  (search → simulate → check_asset_health → screen_post_action → apply), and
  narrates each step.
- **Baseline** (for benchmark): scoped brute-force topology search + do-nothing
  (`bench/benchmark.py`).

## Demo video

The cut screen recording is checked in at:

```text
artifacts/voltify.mp4
```
