# Handoff - grid-agent multi-agent demo

## Current Goal
Build the Voltify Grid Advisor Ring on top of the existing Grid Operations
agent. The Ops agent remains the only actor that mutates Grid2Op state; advisor
agents write constraints, verdicts, and decisions through file artifacts.

Primary spec: `docs/MULTI_AGENT_SPEC.md`.

## Current State

The single-agent 118-bus spine exists under `grid-agent/agent/`:

- `agent/main.py` runs the OpenAI-compatible tool loop against the local model.
- `agent/tools.py` owns Grid2Op, the server-side action registry, and tool
  schemas.
- `agent/artifacts.py` writes `artifacts/run/steps.json` for the UI.
- `ui/index.html` polls the file artifacts and renders the grid/feed.
- `bench/screening.py` is the older standalone N-1 screening script.

The multi-agent work now has items 1 and 2 from `docs/MULTI_AGENT_SPEC.md` started:

1. Blackboard + feed `agent` field + UI lanes.
2. Scenario 6 Screening advisor via `screen_post_action(action_id)`.

## Changes In Working Tree

Modified:

- `agent/artifacts.py`
  - Initializes `artifacts/run/blackboard.json`.
  - Adds default `agent` to every step: `operator` for operator messages,
    `ops` otherwise.

- `agent/main.py`
  - Preserves structured operator decision payloads from `inbox.json`.
  - Writes `decision` items to the blackboard.
  - Renders `screen_post_action` tool results as `agent: "screening"`,
    `kind: "verdict"` feed messages.

- `agent/prompts.py`
  - Adds protocol: Ops must call `screen_post_action(action_id)` after
    `simulate_action` and before `apply_action`.
  - If Screening returns `n1_secure: false`, Ops must stop and ask for human
    authority before applying.
  - Tells Ops to read blackboard summaries from `get_grid_state`.

- `agent/tools.py`
  - Adds `Blackboard` integration.
  - Exposes compact blackboard state through `get_grid_state`.
  - Adds `screen_post_action(action_id)` to dispatcher and tool schema.
  - Writes Screening verdict summaries to `blackboard.json`.

- `ui/index.html`
  - Adds visible agent lanes/classes for `ops`, `operator`, and `screening`.
  - Allows typed JSON decision payloads through the input if they start with
    `{` and have `"kind": "decision"`.

- `ui/serve.py`
  - Preserves structured decision payloads instead of reducing every inbox item
    to `{"text": ...}`.

- `tests/test_artifacts.py`
  - Covers agent tagging and blackboard initialization.

- `tests/test_tools.py`
  - Covers schema update and real `screen_post_action` behavior.

New/untracked:

- `docs/MULTI_AGENT_SPEC.md`
- `agent/advisors/__init__.py`
- `agent/advisors/blackboard.py`
- `agent/advisors/screening.py`

## Important Behavior

`screen_post_action(action_id)` applies the candidate to an environment copy,
then screens every in-service single-line outage by stepping copied envs. It
does not mutate the real Ops env.

Current verified demo behavior for the best sub-67 candidate:

- Candidate: `a-067-2`
- Post-action max rho: `0.79`
- Screened outages: `186`
- Insecure outages: `26`
- `n1_secure: false`
- Worst next contingency currently reported by the solver: line `6`
  (`Storm's End Tie UW 70 -> Qarth Stub UW 72`), which diverges post-action.

Do not script or narrate the spec's illustrative line `154` trap unless a later
solver run actually verifies it. In the current repo state, line `154` is not
the trap for the current best action.

`recovery_action_exists` is deliberately `null` with note
`"not searched by screen_post_action"`. We do not yet run a recovery search
after the second contingency, so the code must not claim one exists or does not
exist.

## Verification Already Run

Passed:

```bash
uv run pytest grid-agent/tests
```

Result: `17 passed, 1 warning in ~50s`.

Passed:

```bash
uv run python -m py_compile \
  grid-agent/agent/main.py \
  grid-agent/agent/tools.py \
  grid-agent/agent/artifacts.py \
  grid-agent/agent/advisors/blackboard.py \
  grid-agent/agent/advisors/screening.py \
  grid-agent/ui/serve.py
```

Could not run:

```bash
uv run ruff check grid-agent/agent grid-agent/tests grid-agent/ui
```

Reason: `ruff` executable is not installed in the current environment.

## How To Run

From repo root:

```bash
uv run python grid-agent/ui/serve.py
```

Then in another terminal:

```bash
cd grid-agent
.venv/bin/python -m agent.main --inbox
```

UI:

```text
http://localhost:8000/ui/index.html
```

The agent still expects the local OpenAI-compatible model endpoint from
`agent/config.py`:

```text
http://localhost:8003/v1
mlx-community/gemma-4-26B-A4B-it-qat-4bit
```

## Next Steps

1. Run an end-to-end UI rehearsal with the local model:
   - Operator asks the agent to inspect/remediate.
   - Ops should call `get_grid_state`, `search_topology_actions`,
     `simulate_action`, then `screen_post_action`.
   - If Screening returns `n1_secure: false`, Ops should stop and ask for
     operator authority instead of calling `apply_action`.

2. Add explicit decision handling for `accept_fragile`:
   - Current inbox preserves and stores decision payloads, but there is no
     deterministic policy layer clearing a Screening hold.
   - The prompt may be enough for the model, but for demo safety a small
     helper should detect a matching `accept_fragile` decision and allow the
     next `apply_action`.

3. Build `Scenario 1 - Weather derate`:
   - Add `agent/advisors/weather.py`.
   - Add `scenarios/weather.json`.
   - Emit blackboard constraint:
     `{"from":"weather","kind":"derate","line_id":177,"pct":8,...}`.
   - Fold derates into Ops urgency/threshold narration.

4. Build `Scenario 2 - Asset veto` after decision plumbing is demo-stable:
   - Add `scenarios/assets.json`.
   - Add `check_asset_health(action_id)`.
   - Enforce block-until-human for asset vetoes.

5. Keep the blackboard compact in `get_grid_state`.
   - Full details can live in `blackboard.json`.
   - Tool responses must stay under `MAX_TOOL_RESULT_CHARS`, or dispatch will
     truncate and tests will fail.

## Caveats

- Design and handoff docs now live under `docs/`.
- The Screening regression is intentionally slow because it performs 186 env
  copy/step checks. Current full test suite takes about 50 seconds.
- Grid2Op warns that `numba` is not installed. Tests still pass; performance
  may improve if installed later.
