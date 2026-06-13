# MULTI_AGENT_SPEC — Voltify Grid Advisor Ring

Extends `SPEC.md` (the single Grid Operations Agent) into a multi-agent system.
The Ops agent stays the spine — same Grid2Op env, same tool layer, same
file-based UI. This document adds an **advisor ring** around it and the
**human-in-the-loop** authority model.

> **Thesis (closing slide):** Each agent owns one slice of reality. The
> operator is the only one who can weigh them against each other. We are not
> replacing the operator — we are giving them expert colleagues who each see
> one thing clearly and disagree out loud.

---

## 1. Roles at a glance

| Agent | Owns | Authority over Ops | Backed by (24h) |
|-------|------|--------------------|-----------------|
| **Grid Operations** (exists) | Live state, topology search, physics sim | Proposes & applies switching | Real — Grid2Op |
| **Weather / Environment** | Forecasts, lightning cells, wind, ambient temp → thermal rating | **Constrains** — changes what counts as safe | Scripted timeline + real derate math |
| **Asset Health** | Equipment condition, breaker cycle budget, PD flags, cumulative wear | **Vetoes** — blocks an action, routes to human | Scripted asset table + wear counter |
| **Market / Dispatch** | Redispatch cost, balancing price, generator availability | **Prices** — turns the residual gap into euros | Scripted cost table + simple merit order |
| **Field Coordination** | Crew location, work orders, lockouts, clear-times | **Constrains** — locks substations, frees them on a clock | Scripted crew roster + sim clock |
| **Contingency Screening** | N-1 security of the *post-action* state | **Holds** — flags a fix that is N-0 safe but N-1 fragile | Real — reuses `bench/screening.py` |

The **operator (human)** holds the authority none of the agents have:
approving an expensive action, accepting a calculated risk, overriding a veto
with accountability, choosing margin-now vs resilience-later.

> **Framing note.** Architecturally the Ops agent is the *spine / assistant
> core*, not a "colleague." The five colleagues of the pitch tagline are the
> advisor ring: **Weather, Asset Health, Market, Field, Screening.** That makes
> "five expert colleagues" land exactly. Keep the slide on five advisors; Ops
> is the operator's own hands.

---

## 2. Architecture — spine + advisor ring of real agents

Each advisor is a **real LLM agent**: its own system prompt, its own domain
context/memory, its own reasoning. They genuinely disagree out loud — that is
the thesis, not a rules engine wearing a chat face.

What keeps them grounded and stage-safe is **shape**, not "no LLM":

```
advisor = own system prompt  +  own tool/data backend  +  single-shot verdict
```

- **Single-shot, not a loop.** Ops runs the one heavy 12-iteration tool-call
  loop (it mutates the grid). An advisor is *reactive*: one trigger → one or two
  tool calls → one verdict to the blackboard. So the system is **1 heavy loop +
  N cheap single-shot agent calls**, not 6 concurrent loops. Cheap on the 4-bit
  local model; same endpoint, different system prompt = a different agent.
- **Grounded by the backend, not by removing the LLM.** The invariant is
  unchanged: the LLM never invents a number, only selects from tool results. A
  Weather agent calls `get_thermal_rating(177)` and reasons "below nameplate →
  derate, escalate"; the °C and the % come from the tool, the *judgment* is the
  agent's. Every euro, every cycle-count, every derate is a backend value the
  agent narrates — never an estimate.
- **Separate state is real.** Asset Health's cross-incident wear counter,
  Market's merit order, Field's roster+clock are genuinely per-agent memory, not
  one process faking six voices.
- **Stage determinism.** Live demo runs advisors at **temp 0**, with a fixtured
  replay path so a flaky token stream can't break the show. They reason for
  real in dev; the stage run is pinned.

Only Ops holds `apply_action` — the advisors advise, constrain, veto, price, and
hold, but never touch the grid.

### 2.1 Blackboard (the message bus)

Reuse the file-based pattern already in `SPEC.md` (§6). One shared JSON file
the Ops loop reads at the top of every iteration:

```
artifacts/run/blackboard.json
```

```json
{
  "constraints": [
    {"from": "weather", "kind": "derate", "line_id": 177, "pct": 8,
     "reason": "ambient 34°C rising, real thermal rating below nameplate",
     "ttl_steps": null},
    {"from": "field", "kind": "exclude_sub", "sub": 67,
     "reason": "crew on site, safety lockout", "clears_at": "14:30"}
  ],
  "vetoes": [
    {"from": "asset_health", "action_id": "a-080-03", "level": "block",
     "override": "human", "reason": "sub 80 breaker: partial-discharge flag, "
     "switching under fault not authorized"}
  ],
  "quotes": [],
  "screening_verdicts": [],
  "availability": [
    {"from": "field", "crew": "C1", "at_sub": 67, "status": "on_site",
     "clears_at": "14:30"}
  ],
  "clock": "14:18"
}
```

The Ops loop folds these into its existing tool params and decision flow:

- `derate` → adjusts the rho threshold / urgency for the named line.
- `exclude_sub` → passed straight to `search_topology_actions`'
  `exclude_substations` (already exists).
- `veto` on a chosen `action_id` → Ops **may not** call `apply_action` until an
  operator `decision` clears it.
- `quote` → Ops surfaces the euro menu to the operator.
- `screening_verdict` → Ops must request one before any `apply_action`, and
  surface a `fragile` verdict to the operator.

### 2.2 Message types into the feed (`steps.json` extension)

Add one field to the existing step object (§6 of `SPEC.md`): `agent`.

```json
{
  "step": 5,
  "agent": "asset_health",          // ops | weather | asset_health | market | field | screening | operator
  "kind": "veto",                   // existing kinds + : constraint | veto | quote | verdict | escalation | decision
  "summary": "VETO sub 80 — breaker PD flag, needs human sign-off",
  "text": "...full voice line...",
  "refs": {"action_id": "a-080-03"},
  "grid_status": "overloaded",
  "max_rho": 1.31
}
```

The UI renders each agent in its own lane/color so the "colleagues disagreeing
out loud" reads visually. Operator decisions still arrive via `inbox.json`
(§6); add a `decision` payload shape (§3.7).

### 2.3 How Ops consults an advisor

Two trigger modes, both file-driven, no new infra:

1. **Reactive (push):** an advisor watches the blackboard / clock and posts a
   constraint or veto when its trigger fires (lightning ETA, crew on site).
   For the demo these are *scripted to fire on a given step* — deterministic,
   rehearsable.
2. **Pull (Ops asks):** Ops calls a new tool that consults an advisor and
   writes the result to the blackboard + feed. Three new tools (§3).

---

## 3. New tool layer (additive to `SPEC.md` §3)

The four existing tools are untouched. Add three advisor-consult tools the Ops
agent can call, plus a decision intake. **Each consult tool dispatches to the
real advisor agent** (an LLM call with that agent's system prompt + backend),
which reasons over its domain and returns the verdict below. The tool is the
wire; the advisor is the mind. Each returns compact JSON and writes a feed step
in the advisor's own voice.

### 3.1 `check_asset_health(action_id)`  → Asset Health agent

```json
{"name": "check_asset_health",
 "description": "Ask the Asset Health agent whether a proposed action is authorized given equipment condition and remaining switching-cycle budget. Returns ok | warn | block.",
 "parameters": {"type": "object",
   "properties": {"action_id": {"type": "string"}},
   "required": ["action_id"]}}
```

Returns:

```json
{"action_id": "a-080-03", "verdict": "block", "override": "human",
 "substation": 80,
 "reason": "breaker B-80 partial-discharge flag (last inspection); switching under fault not authorized",
 "cycle_budget": {"breaker": "B-80", "ops_remaining_month": 3}}
```

Backend = a static `assets.json` table (per-substation flags, monthly cycle
budget, a wear counter incremented on each `apply_action`); the Asset Health
agent reasons over it to decide ok/warn/block and phrase the reason. `block` →
Ops cannot apply without an operator `decision` clearing it.

### 3.2 `price_residual(gap_mw, options?)`  → Market agent

Called when topology alone cannot reach rho < 1.0 (the residual gap).

```json
{"name": "price_residual",
 "description": "Ask the Market agent to price the remaining overload gap that switching cannot close: redispatch and curtailment options with euro cost and regulatory consequences.",
 "parameters": {"type": "object",
   "properties": {"gap_mw": {"type": "number"},
     "post_topology_rho": {"type": "number"}},
   "required": ["gap_mw"]}}
```

Returns:

```json
{"gap_mw": 40, "post_topology_rho": 1.05,
 "options": [
   {"id": "rd-X-down", "action": "redispatch generator X down 40MW",
    "euro_per_hour": 4200, "renewable": false, "reporting": false},
   {"id": "curt-wind", "action": "curtail 12MW wind",
    "euro_per_hour": 1800, "renewable": true, "reporting": true,
    "note": "renewable curtailment — reporting obligation"}],
 "physics_note": "Market does not verify these reach rho<1.0; Ops must simulate the chosen MW as a redispatch probe."}
```

Backend = cost table from `prompts.py` + a tiny merit order in `market.json`;
the Market agent reasons over it to assemble and rank the option menu.
**Honesty hook:** the euro number is a data lookup; the *rho effect* of the MW
change is only real if Ops simulates it. If redispatch sim is not wired, Ops
states the limit ("I priced it; I have not simulated the MW effect on this
grid") — same discipline as `SPEC.md` §3.4.

### 3.3 `screen_post_action(action_id)`  → Contingency Screening agent

The strongest *real* beat — reuses `bench/screening.py`.

```json
{"name": "screen_post_action",
 "description": "Before applying a proposed fix, ask the Screening agent to re-run N-1 screening against the POST-action topology and report whether the fix is itself N-1 secure.",
 "parameters": {"type": "object",
   "properties": {"action_id": {"type": "string"}},
   "required": ["action_id"]}}
```

Returns:

```json
{"action_id": "a-067-12", "post_action_rho": 0.80,
 "n1_secure": false,
 "worst_next_contingency": {"line_id": 154, "post_trip_rho": 1.31,
   "recovery_action_exists": false},
 "baseline_comparison": "current topology absorbs a 154 trip; post-split topology cannot",
 "screened_outages": 186, "screen_seconds": 6}
```

Backend = apply the candidate to a **copy** of the env, run the existing
186-outage screening on the resulting topology, compare against the pre-action
screening; the Screening agent interprets the delta and names the killer
contingency. `n1_secure=false` → Ops must surface the trade-off to the operator
before apply.

### 3.4 Weather & Field

Same real-agent shape, but **reactive emitters** rather than pull-tools (their
triggers are time/forecast based, so they fire on their own rather than waiting
for Ops to ask). Each is still an LLM agent with its own prompt + backend;
`advisors/weather.py` and `advisors/field.py` run the single-shot agent on a
trigger and post its verdict to the blackboard:

- Weather: `derate(line, pct)` from ambient-temp curve; `predict_trip(lines, eta)`
  from a lightning timeline in `weather.json`. Derate math is real (a thermal
  rating curve); the timeline is scripted.
- Field: `exclude_sub(sub, clears_at)` from `crew.json`; advances a sim clock so
  it can *free* the substation ("crew clears 14:30, can you hold 12 min?").

If a pull interface is wanted for Q&A ("Field, when does 67 free up?"), add a
trivial `ask_field(sub)` returning the roster entry — optional, cut first.

### 3.5 Asset-wear (longer horizon, same Asset Health agent)

`check_asset_health` increments a per-breaker wear counter on every real
`apply_action`. Across a benchmark run of many incidents it surfaces the
pattern the Ops agent cannot see (Ops sees each incident fresh): "this is the
40th switch at sub 67 this month; cheapest path today, cheapest path to a
breaker failure if you keep choosing it." Demo: run the benchmark, show the
counter climbing, show the warning fire. Real, cheap, no new physics.

### 3.6 Weather derate effect on Ops

The derate does not change the solver; it changes the **threshold**. Ops applies
`effective_limit = nameplate * (1 - pct/100)` for the derated line, so a rho the
Ops agent alone called 1.30-borderline is re-scored against the lowered limit
and escalates "monitor → act now." One input, different decision — the whole
point of Scenario 1.

### 3.7 Operator decision intake (`inbox.json`)

Operator messages already drive Ops (§6). Add a structured `decision` shape for
the human-authority beats:

```json
{"kind": "decision", "ref": "a-080-03",
 "choice": "override_veto" | "take_second_best" | "dispatch_crew"
          | "pick_market_option" | "hold_and_wait" | "accept_fragile",
 "option_id": "curt-wind",      // when choice == pick_market_option
 "note": "operator accepts asset risk, signed: M.D."}
```

Ops maps `choice` to its next action: clear the veto and apply, re-search with
the offending sub excluded, fold a market option into a hybrid action, or hold
until the Field clear-time.

---

## 4. Scenarios (build priority)

Each: trigger · who talks to whom · where the human is required · resolution.
Recommended build set in **bold**.

### Scenario 1 — Heat derating *(information boundary)* — **BUILD (opener)**

- **Trigger:** Line 177 at rho 1.30, Ops-alone calls it borderline. Weather
  posts `derate(177, 8%)`: ambient 34°C rising, real rating below nameplate.
- **Flow:** Weather → blackboard. Ops re-scores 177 against the lowered limit,
  escalates monitor→act-now, runs the scoped search, applies the sub-67 split.
- **Human:** none. Two agents making each other smarter.
- **Resolution:** the rescue you already have — but the *reason it was urgent*
  came from another agent. One new input, whole different decision.
- **Why first:** cheapest possible second-agent demo; no human, no new physics,
  reuses the proven arc.

### Scenario 2 — Predicted fault + the veto *(information + authority)* — **BUILD (headline)**

- **Trigger:** Weather forecasts a lightning cell over the northern corridor in
  ~20 min; lines 11–13 at elevated strike risk. Nothing has failed yet.
- **Flow:** Weather → Ops ("11–13 will likely trip, pre-position"). Ops searches
  for a topology robust if 11–13 trip; best routes through sub 80. Ops calls
  `check_asset_health("a-080-..")` → **block** (PD flag, not authorized under
  fault without sign-off).
- **Human:** required. Ops surfaces: *"Best pre-position needs sub 80. Asset
  Health flagged it — I can't authorize alone. (a) you accept the asset risk and
  sign off, (b) I find a second-best with less margin, (c) dispatch a crew to
  inspect first — Field says 40 min."* Operator chooses via `decision`.
- **Resolution:** branches by the human choice — that **is** the point. The
  agent frames the trade-off and routes the decision to the only entity allowed
  to make it.
- **Why headline:** predictive input + inter-agent veto + human-in-the-loop in
  one beat. The whole thesis in one scenario.

### Scenario 3 — Expensive reconciliation *(objective boundary)* — BUILD if time

- **Trigger:** N-1 event where no zero-cost topology action fully rescues —
  switching reaches rho 1.05, still over.
- **Flow:** Ops → `price_residual(gap_mw, 1.05)`. Market returns the menu:
  redispatch gen X down 40MW ≈ €4,200/h, **or** curtail 12MW wind ≈ €1,800/h but
  renewable + reporting obligation.
- **Human:** required — cost/regulatory values call. Cheaper-but-curtails vs
  pricier-but-clean is not a physics call.
- **Resolution:** hybrid action — topology to 1.05, then the human-chosen market
  action closes it. Two agents' outputs combined under human judgment.

### Scenario 4 — Timing negotiation *(authority + coordination)* — BUILD if time

- **Trigger:** Operator wants to switch at sub 67. Field: crew physically on 67
  now → safety lockout, cannot, full stop.
- **Flow:** Ops → Field (`exclude_sub 67, clears_at 14:30`). Ops to operator:
  *"67 is your best fix, safety-locked 12 more min. Can the grid hold? I project
  line 177 stays under 1.4 for ~15 min at current load — yes, with margin.
  Recommend hold, switch at 14:30. Or take second-best at sub 64 now, less
  margin. Your call."*
- **Human:** required — accept wait-with-risk, or take worse-but-now.
- **Resolution:** either path defensible; the agent quantifies the wait so the
  human decides on numbers, not vibes. The "hold N minutes" projection reuses
  the existing stability-check replay (`SPEC.md` §3.4).

### Scenario 6 (the trap) — The fix that strands you *(post-action N-1)* — **BUILD (real & strong)**

- **Trigger:** Line 177 overloaded at rho 1.31. Ops finds the clean fix —
  bus-split at sub 67 — rho drops to 0.80, grid N-0 secure. Single agent
  declares victory.
- **Hidden cost:** the split removed redundancy at 67. Grid looks healthy but is
  now **N-1 fragile**: a trip on line 154 (fine right now) cascades with no
  recovery action. The fix set a trap for the second contingency.
- **Flow:** Ops → `screen_post_action("a-067-12")`. Screening: *"hold. Re-ran
  N-1 on your proposed post-fix topology. N-0 secure but N-1 fragile: with 67
  split, a 154 trip cascades, no recovery exists. Current topology absorbs a 154
  trip; your fix can't."*
- **Human:** required — take the clean fix and accept reduced redundancy for the
  shift, **or** take the second-best at sub 64 holding rho 0.94 (less margin now)
  but keeping N-1 security against the next failure. Margin-now vs
  resilience-later — neither agent can make this call alone.
- **Why build:** the screening is **real code already in the repo**
  (`bench/screening.py`). Highest credibility-per-effort beat. Echoes 2003-style
  cascades where each local fix was locally correct, globally degrading.

### Scenario 5 — Cascade under conflicting agents *(all boundaries)* — **ROADMAP ONLY, DO NOT BUILD**

A real cascade where every agent constrains a different lever at once: line
trips, weather says more coming, one fix vetoed on asset grounds, the only clean
alternative is expensive, a crew is mid-job on the substation you'd want.
Unbuildable in the timebox — and the perfect closing slide: *"five expert
colleagues who each see one thing clearly and disagree out loud. We don't
replace the operator; we give them the colleagues."*

---

## 5. What is real vs scripted

| Real (solver / repo code) | Scripted (data file) |
|---|---|
| Grid state, search, simulate, apply (Ops, exists) | Lightning timeline, forecast ETAs (`weather.json`) |
| Weather **derate math** (thermal rating curve) | Asset flags / PD / cycle budgets (`assets.json`) |
| Post-action N-1 screening (`screen_post_action`) | Cost table & merit order (`market.json`) |
| Stability-hold projection (Scenario 4) | Crew roster, lockouts, clear-times (`crew.json`) |
| Asset wear counter (increments on real apply) | Sim clock advance |

Rule (unchanged from `SPEC.md`): **every number narrated comes from a tool
result or a data table; no advisor estimates.** A scripted euro figure is a
lookup, stated as such; a rho effect is only claimed if the solver produced it.

---

## 6. File layout (additive)

```
grid-agent/
  agent/
    tools.py          # + check_asset_health, price_residual, screen_post_action
    advisors/
      __init__.py
      weather.py      # derate curve (real) + scripted timeline → blackboard
      asset_health.py # assets.json + wear counter, veto logic
      market.py       # cost table + merit order, residual pricing
      field.py        # crew roster + sim clock, exclude/free subs
      screening.py    # thin wrapper over bench/screening.py on post-action env copy
      blackboard.py   # read/write artifacts/run/blackboard.json
    prompts.py        # + advisor-awareness: when to consult each, veto/decision protocol
  scenarios/
    weather.json  assets.json  market.json  crew.json   # scripted cores
  ui/
    index.html        # + per-agent lanes/colors, decision buttons
```

Ops system prompt gains a short protocol block: *consult Screening before any
apply; respect Asset Health vetoes (route block→human); when topology can't
reach rho<1.0, price the residual with Market; honor Field exclusions and report
clear-times; fold Weather derates into thresholds.* No code branching per
scenario — the constraints arrive as data, exactly like the existing
"sub 67 unavailable" twist.

---

## 7. Build order (on top of the existing 6-task plan)

The single-agent demo (`SPEC.md` §9 tasks 1–3) must work first — it is the
spine. Then:

1. **Blackboard + feed `agent` field + UI lanes** — plumbing for every scenario.
   (one evening's work, unlocks all beats)
2. **Scenario 6 — Screening** — wrap `bench/screening.py`, add
   `screen_post_action`, wire the post-action env copy. *Real, highest payoff,
   build first of the advisor beats.*
3. **Scenario 1 — Weather derate** — derate curve + threshold re-score. No human,
   cheap, great opener.
4. **Scenario 2 — Asset veto** — `assets.json`, `check_asset_health`, veto→human
   decision flow. The headline; build once the decision-intake plumbing (3.7) is
   proven by Scenario 6/1.
5. **Scenario 3 — Market** and **Scenario 4 — Field** — parallelizable, each a
   data file + one tool/emitter. Build whichever the rehearsal wants; both are
   "if time."
6. **Asset-wear over benchmark** — counter + warning, demoed over the existing
   benchmark run. Slide-grade, near-free.

**Cut line:** spine (SPEC §9) is the demo floor. Scenario 6 + Scenario 1 are the
minimum multi-agent story (one real, one cheap). Scenario 2 is the headline if
the decision plumbing holds. 3/4 are bonus beats. 5 is the closing slide.

---

## 8. Verification

- **Blackboard:** Ops folds a scripted `derate`/`exclude_sub` into its next
  search params with no code branch (assert via golden transcript).
- **Scenario 1:** with the derate posted, Ops escalates 177 from monitor to act
  and rescues; without it, Ops calls 177 borderline. Diff the two runs.
- **Scenario 2:** `check_asset_health` returns `block` for the sub-80 action;
  Ops does **not** call `apply_action` until an `override_veto` decision; each of
  (a)/(b)/(c) reaches a defensible end state. Scripted, rehearsed.
- **Scenario 6:** `screen_post_action` on the sub-67 split returns
  `n1_secure=false` with line 154 as the killer; the sub-64 second-best returns
  `n1_secure=true` at rho 0.94. **Verify against real screening output before
  the demo** — this is the credibility beat, it must be true, not staged.
- **Grounding invariant (all scenarios):** transcript contains no number absent
  from a tool result or a named data table. Manual check, same as SPEC §10.
- **Demo resilience:** full run, network disabled, localhost only.
