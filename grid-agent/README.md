# Grid Operation Agent (Challenge 5)

LLM agent that returns an overloaded power grid to a safe state while narrating
its reasoning. Built on Grid2Op with a 118-bus demo scenario and a multi-agent
advisor ring.

## Project layout

```text
agent/       Runtime agent, tools, prompts, advisor backends
bench/       Benchmark and N-1 screening utilities
data/        Small checked-in data inputs
docs/        Product/spec/planning/handoff documents
scenarios/   Scripted demo scenario data
scripts/     One-off spike and verification scripts
tests/       Pytest suite
ui/          Static demo UI and local server
artifacts/   Checked-in demo outputs, screenshots, and video
```

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
.venv/bin/python scripts/spike_overload_rescue.py
```

Note: system python3 is 3.9 (too old), homebrew is 3.14 (too new for wheels).
Use uv-managed 3.12.

## Demo

From this directory, run:

```bash
make demo
```

Then open `http://localhost:8000/ui/index.html`. The Makefile starts the
static UI server and runs the agent in inbox mode so messages sent from the
web input are consumed by the agent.

Useful separate targets:

```bash
make ui      # serve only the web UI
make agent   # run only the inbox agent
make test    # run the test suite
```

## Architecture sketch

- **Env**: Grid2Op `l2rpn_case14_sandbox` (later: bigger L2RPN envs)
- **Agent tools**:
  - `get_grid_state` — loads, gens, line flows, rho per line
  - `search_topology_actions` — find grounded candidate topology actions
  - `simulate_action` — dry-run a registered candidate action
  - `check_asset_health` — ask Asset Health for veto/warn/ok
  - `screen_post_action` — ask Screening for post-action N-1 verdict
  - `apply_action` — step the env
- **Agent loop**: local OpenAI-compatible model reasons over tool results,
  simulates candidates, consults advisors, applies only authorized actions,
  and narrates each step.
- **Baseline** (for benchmark slide): brute-force topology search
  (already in spike) + do-nothing
- **Scenarios** (energy expert): pick dramatic-but-solvable overload cases,
  define safe-state metric

## Demo video

The cut screen recording is checked in at:

```text
artifacts/voltify.mp4
```
