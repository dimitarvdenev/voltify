# SPEC — Grid Operation Agent (Voltify)

Technical spec implementing `PRD.md`. The PRD owns the what/why; this document
owns the how: architecture, tool schemas, loop design, file layout, data
contracts. Grounded in the verified spike (`verify_118_arc.py`,
`scenarios/arc_118.json`).

## 1. Architecture overview

```
┌─────────────┐   operator msg    ┌──────────────────────────┐
│  Demo UI    │ ────────────────▶ │  Agent loop (main.py)    │
│ index.html  │                   │  OpenAI tool-call loop   │
│ (polls      │ ◀──────────────── │  vs local LLM :8003      │
│  steps.json)│   step artifacts  └──────────┬───────────────┘
└─────────────┘   + plotly renders           │ tool calls
                                  ┌──────────▼───────────────┐
                                  │  Tool layer (tools.py)   │
                                  │  Grid2Op env + action    │
                                  │  registry (server-side)  │
                                  └──────────────────────────┘
```

- **One process** runs the agent loop and tool layer (plain Python, no MCP,
  no server framework). The UI is a static page polling JSON artifacts.
- **LLM:** `mlx-community/gemma-4-26B-A4B-it-qat-4bit` via OpenAI-compatible
  endpoint `http://localhost:8003/v1` (verified: native tool calling,
  multi-turn round-trips, ~77 tok/s). `openai` Python client, plain
  chat-completions tool loop.
- **Environment:** `l2rpn_neurips_2020_track2_small` (118 buses), local data
  dir `data_grid2op/` via `grid2op.change_local_dir()`. Demo scenario is
  chronic 0, crisis-at-open (line 177 at rho 1.30, do-nothing blackout at
  step 4) per `scenarios/arc_118.json`.
- **Time model:** one-shot snapshot rescue (PRD §9). Freeze post-contingency
  state, search/simulate/apply, verify. No multi-step episodes.

### Core invariant: physics grounding

Every number the LLM narrates comes from a tool result. The LLM never
constructs actions — it selects `action_id`s from candidates the search tool
returned. Actions live in a **server-side registry** (dict `action_id →
Grid2Op action object`); the LLM only ever sees ids and summaries. The
grounding test showed the 4-bit model produces no-op bus assignments unaided;
the registry makes that failure mode impossible.

## 2. File layout

```
grid-agent/
  agent/
    __init__.py
    main.py          # entrypoint: scenario load, chat loop, operator input
    llm.py           # OpenAI client wrapper (base_url, model, tool-loop helper)
    tools.py         # 4 tool implementations over Grid2Op + action registry
    prompts.py       # system prompt, regulation excerpt, cost table
    render.py        # plotly per-step renders (full grid + zoomed view)
    artifacts.py     # step JSON writer (UI data contract, §6)
  ui/
    index.html       # demo page: grid render left, narration feed right
  bench/
    screening.py     # deliverable 2: 186-outage N-1 table
    benchmark.py     # deliverable 3: agent vs scoped brute-force vs do-nothing
  scenarios/         # arc_118.json (exists), crib-sheet prompts
  artifacts/         # spike renders (exist) + per-run step output
  data_grid2op/      # downloaded env (exists)
```

Existing spike scripts (`spike_*.py`, `verify_118_arc.py`) stay untouched at
the top level as reference.

## 3. Tool layer

Four tools. All return compact JSON strings — top-k summaries, never full
186-line dumps (local model context budget). Shared helpers lifted from
`verify_118_arc.py`: `scoped_substations()` (overload endpoints + n-hop
growth), `MAX_ACTIONS_PER_SUB = 600` cap.

### 3.1 `get_grid_state`

Inspect the current (real) grid state. No parameters.

```json
{
  "name": "get_grid_state",
  "description": "Current grid state: worst loadings, overloaded lines, disconnected lines. All values from the power-flow solver.",
  "parameters": {"type": "object", "properties": {}, "required": []}
}
```

Returns:

```json
{
  "max_rho": 1.30,
  "n_overloaded": 1,
  "overloaded_lines": [
    {"line_id": 177, "from_sub": 115, "to_sub": 67, "rho": 1.30}
  ],
  "top_loaded_lines": [ /* top 5 by rho, same shape */ ],
  "disconnected_lines": [],
  "candidate_scope_subs": [64, 67, 68, 80, 115]
}
```

`candidate_scope_subs` is the 1-hop neighborhood of the overload — the tool
hands the agent its scoping hint; the agent decides the scope (and shrinks it
under operator constraints).

### 3.2 `search_topology_actions`

Scoped search. The heavy lift; the agent's value is choosing the scope.

```json
{
  "name": "search_topology_actions",
  "description": "Simulate every unitary bus-split at the given substations and return candidates ranked by resulting max line loading. Scope must be small (<=8 substations); the full grid has 72,107 actions and cannot be searched in operator time.",
  "parameters": {
    "type": "object",
    "properties": {
      "substations": {
        "type": "array", "items": {"type": "integer"},
        "description": "Substation ids to search, e.g. the overload neighborhood from get_grid_state."
      },
      "exclude_substations": {
        "type": "array", "items": {"type": "integer"},
        "description": "Substations unavailable for switching (e.g. crew on site). Optional."
      }
    },
    "required": ["substations"]
  }
}
```

Returns (top 5 candidates; failures summarized, not listed):

```json
{
  "actions_simulated": 88,
  "actions_total_grid": 72107,
  "search_seconds": 3.0,
  "skipped_substations": [{"sub": 48, "reason": "65k combos, over cap"}],
  "candidates": [
    {
      "action_id": "a-067-12",
      "substation": 67,
      "description": "bus-split at substation 67",
      "simulated_max_rho": 0.796,
      "simulated_n_overloaded": 0,
      "reconnects_lines": [],
      "switching_ops": 4,
      "cost_class": "switching (~free)"
    }
  ]
}
```

- `reconnects_lines`: the narration gotcha made explicit — a bus assignment
  ≠ 0 implicitly reconnects a disconnected line; the tool computes and
  reports this so the narration can say it.
- `cost_class` comes from the cost table in `prompts.py` (teammate-supplied
  constants): switching ≈ free, redispatch €/MW, curtailment expensive +
  regulatory pain.
- Registry: each candidate's Grid2Op action object is stored under its
  `action_id` for later `simulate_action`/`apply_action` calls.

### 3.3 `simulate_action`

Re-check one candidate (used for follow-ups like "why not redispatch?" and
for the reflection step before apply).

```json
{
  "name": "simulate_action",
  "description": "Simulate a single action from a previous search against the current state. Returns solver results only.",
  "parameters": {
    "type": "object",
    "properties": {
      "action_id": {"type": "string"}
    },
    "required": ["action_id"]
  }
}
```

Returns: `{"action_id", "simulated_max_rho", "simulated_n_overloaded",
"overloaded_lines": [...], "reconnects_lines": [...], "diverged": false}`.

### 3.4 `apply_action`

The only state-mutating tool. Real `env.step()`, then a stability check.

```json
{
  "name": "apply_action",
  "description": "Apply an action to the real grid (not a simulation). Then verify: report post-apply state and whether the grid survives the next steps without intervention.",
  "parameters": {
    "type": "object",
    "properties": {
      "action_id": {"type": "string"}
    },
    "required": ["action_id"]
  }
}
```

Returns: `{"applied": true, "max_rho": 0.806, "n_overloaded": 0,
"stable_steps_checked": 20, "stable": true}`. The stability check replays
do-nothing steps on a copy/forecast where Grid2Op allows; the proven arc
showed 20+ stable steps after the sub-67 split.

**Redispatch:** not a separate tool. The demo's planted "why not redispatch?"
is answered honestly: the system prompt carries a hard rule that action
types not simulated in *this* run must be named as such — "I haven't
simulated redispatch on this grid" — and that results from other grids or
past studies are never quoted as numbers. The agent argues from the cost
table plus its own switching results (which it did measure). The case14
rho-1.9 figure stays out of the prompt entirely: a 4-bit model cannot be
trusted to keep an "attributed as prior measurement" qualifier attached,
and one dropped qualifier on stage breaks the grounding invariant in front
of a judge. Upgrade path (decide at hour ~6, after Task-12 rehearsal): if
the honest answer sounds weak, add 2-3 redispatch probes to the search
tool so the comparison is grounded in this run's solver results.

## 4. Agent loop (`main.py` + `llm.py`)

Plain OpenAI tool-call loop:

```
messages = [system, scenario_brief, operator_msg]
loop (max 12 iterations):
    resp = client.chat.completions.create(model, messages, tools)
    if resp has tool_calls: execute via tools.py, append results, continue
    else: final narration → emit step artifact, await next operator msg
```

- **System prompt** (`prompts.py`): role (transmission grid operator
  assistant), the physics-grounding rule (quote tool numbers only, never
  estimate), narration style (operator language, name the violated limit and
  the governing rule), ~20-line regulation excerpt (N-1 principle, 15-minute
  N-0 restoration window), cost table.
- **Required flow nudge** in the system prompt: inspect → scope → search →
  (optionally re-simulate best) → apply → re-inspect (reflection). If
  post-apply `max_rho >= 1.0`, search again with widened scope (1 more hop).
  Max 2 apply attempts per scenario, then report failure honestly.
- **Operator messages** come from the presenter's input box (UI §6) or stdin;
  the constraint twist ("substation 67 unavailable, crew on site") arrives as
  a normal user message mid-conversation — the agent maps it to
  `exclude_substations` on its next search. No special casing in code; this
  IS the messiness-thesis demo beat.
- **Follow-up Q&A** answered from conversation memory (prior tool results
  stay in `messages`) — no extra infrastructure.
- **Step artifacts:** after every tool result and every narration message,
  `artifacts.py` appends to the run's step file (§6) and `render.py`
  regenerates the current grid renders.

Context budget: tool results are compact by design (§3); the loop also caps
`candidates` at 5 and truncates any tool output above ~1,500 chars defensively.

## 5. Scenario management

- `main.py --scenario arc_118` loads chronic 0 of the 118-bus env. The env
  opens in crisis (no outage injection — crisis-at-open per arc_118.json).
- Scenario file supplies the briefing the agent gets up front (env name,
  chronic, the *fact that* a contingency exists — not its solution) and the
  crib-sheet operator prompts for the presenter.
- Benchmark scenarios (bench/, §7) are the dangerous subset of the 186-outage
  screening table, each one-shot rescued independently.
- Determinism: scenario selection is scripted; no free-form fault injection
  (PRD §9).

## 6. UI / data contract (`ui/index.html`, `artifacts.py`)

Single static page, zero build step, served by `python -m http.server` from
`grid-agent/`. No websockets: the page polls `artifacts/run/steps.json`
every second.

`steps.json` — append-only array of step objects:

```json
{
  "step": 3,
  "kind": "tool",                      // "tool" | "narration" | "operator"
  "tool": "search_topology_actions",   // when kind == "tool"
  "summary": "88 candidates at 5 substations, 3.0s, best rho 0.80",
  "text": "...",                       // narration / operator message text
  "grid_status": "overloaded",         // "overloaded" | "rescued"
  "max_rho": 1.30,
  "render_full": "renders/step3_full.html",
  "render_zoom": "renders/step3_zoom.html"
}
```

Page layout: left pane shows the zoomed render (iframe, swaps per step; full
grid behind a toggle — PRD §10 legibility decision), right pane is the
chat-style feed (operator messages right-aligned, agent narration
left-aligned, tool steps as small status lines). Bottom right: presenter
input box that appends to `artifacts/run/inbox.json`, which `main.py` polls
for the next operator message. Dumb file-based message passing both ways.

Renders (`render.py`): plotly HTML per state change (not per step — only
when the grid actually changes: open, post-apply). Zoom view = overloaded
lines + their substations + 1 hop, reusing the spike plotly path. Red→green
recolor by rho threshold. **Open item: verify zoomed 118-bus render is
projector-legible (PRD §13) — first thing to check once render.py exists.**

## 7. Benchmark & screening (`bench/`)

- `screening.py` (deliverable 2): all 186 single-line N-1 outages on the
  fixed snapshot, classified relative to the stressed baseline (naive rho>1
  marks 184/186 dangerous — use delta-vs-baseline and divergence as the
  danger criteria). Output: `artifacts/screening_118.json` + markdown table.
  Measured budget: ~6 s full screening.
- `benchmark.py` (deliverable 3): over the dangerous subset, three columns —
  agent (full loop, local LLM), scoped brute-force (the `verify_118_arc.py`
  search, no LLM), do-nothing. Metrics per scenario: rescued (rho<1.0 y/n),
  actions taken, wallclock. Blind brute-force (~38 min) is quoted as a
  number, never run. Output: JSON + markdown table for the pitch.
- Honesty rule (PRD §8): brute-force will win on success rate within its
  scope; the table says so, the pitch argues the messiness thesis on top.

## 8. Configuration

`agent/config.py` (or constants at top of `main.py` — whichever is less
ceremony):

```python
LLM_BASE_URL = "http://localhost:8003/v1"
LLM_MODEL = "mlx-community/gemma-4-26B-A4B-it-qat-4bit"
ENV_NAME = "l2rpn_neurips_2020_track2_small"
GRID2OP_LOCAL_DIR = "data_grid2op"      # via grid2op.change_local_dir
MAX_ACTIONS_PER_SUB = 600
TOP_K_CANDIDATES = 5
MAX_LOOP_ITERATIONS = 12
MAX_APPLY_ATTEMPTS = 2
STABILITY_CHECK_STEPS = 20
```

`requirements.txt` gains `openai`. Env quirks (from HANDOFF): Python 3.12
venv via uv; sandbox needs `UV_CACHE_DIR=$TMPDIR/uv-cache`,
`MPLCONFIGDIR=$TMPDIR/mpl`; `numpy<2` pin stays.

## 9. Build order (24h-shaped)

1. **Tool layer + registry** (`tools.py`) — pure refactor of proven spike
   code into the four tools; testable without the LLM.
2. **Agent loop** (`llm.py`, `main.py`, `prompts.py`) — wire to local model,
   reproduce the arc_118 rescue end-to-end via the LLM choosing the action.
   *This is the keystone; everything after is additive.*
3. **Step artifacts + UI** (`artifacts.py`, `render.py`, `index.html`) —
   verify render legibility immediately.
4. **Constraint twist** — verify second-best rescue with sub 67 excluded
   (PRD §13 open item) using the tool layer directly before trusting it on
   stage.
5. **Screening + benchmark** (`bench/`).
6. Crib sheet, narration polish with teammate, pitch assets.

Cut line if time runs out: 1–3 are the demo; 4 is the best beat (verify
early, cheap); 5 is a slide; 6 is human work in parallel.

## 10. Verification

- **Tool layer:** golden test — replay arc_118 through the tools
  (`get_grid_state` shows line 177 at 1.30; scoped search over
  [64, 67, 68, 80, 115] finds the sub-67 split at rho 0.796; apply yields
  0.806 and 20 stable steps). Must match `scenarios/arc_118.json`.
- **Agent loop:** end-to-end run rescues the demo scenario with zero
  hand-holding, and the transcript contains no number absent from tool
  results (manual check; the grounding invariant).
- **Constraint twist:** scripted run with the exclusion message reaches
  rho < 1.0 via a different substation — verified before the demo, with the
  result saved to `scenarios/` as the second-best record.
- **Demo resilience:** full run with network disabled (localhost only).
