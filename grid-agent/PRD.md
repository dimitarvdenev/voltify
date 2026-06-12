# PRD — Grid Operation Agent (Voltify)

Consolidated from the official E.ON challenge text (**Direction 1: Grid
Operation Agents** — note: `../CHALLENGES.md` is an earlier draft with
different numbering), `HANDOFF.md`, `PRIOR_ART.md`, `README.md`, and the
local-LLM grounding session. This is the **what/why**; the technical spec
(tool schemas, loop design, file layout) is a separate document.

## 1. Problem

Grid operators must keep the network "N-1 secure": it has to survive the loss
of any single line or generator. When a line trips, the operator has minutes
to react and needs safe, low-cost remedial actions — from a menu of
**switching, redispatch, transformer taps, and curtailment** — with reasoning
they can trust. Today's options are manual expertise (slow, scarce) or RL
agents from L2RPN research (black boxes, no explanation, not trusted in
control rooms).

## 2. Product

An LLM agent that **returns an overloaded power grid to a safe state while
narrating its reasoning in operator language** — cost-aware, regulation-aware,
and physics-grounded (every number comes from the power-flow solver, never
from the LLM).

**Positioning vs prior art (X-GridAgent, arXiv:2512.20789, cited by the
challenge):** existing systems *analyze* the grid and answer questions; ours
*operates* it. The action/remediation layer is exactly what the closest paper
defers to future work.

> Pitch line: "X-GridAgent answers questions about the grid. Ours operates it."

## 3. Users

- **Primary (demo persona):** transmission grid operator in a control room
  facing an N-1 contingency.
- **Actual audience:** hackathon judges (energy industry + AI). The demo must
  be legible to both in one viewing.

## 4. Core user journey (the demo arc — verified feasible in spike)

1. Grid healthy (IEEE case14, max line loading rho 0.92).
2. N-1 event: line 17 (substation 4→5) lost → 4 lines overloaded, rho 1.91.
3. Agent inspects state, searches/simulates candidate actions, picks a
   bus-split at substation 5, applies it → rho 0.83, zero overloads.
4. Agent narrates each step: which limit is violated, what it tried, why the
   chosen action wins across the full operator menu — switching ≈ free,
   redispatch priced per MW, curtailment expensive + regulatory pain,
   transformer taps noted where relevant — and which rule requires acting
   (N-1 principle, thermal limits).
5. Operator asks a follow-up ("why not redispatch?") — agent answers from its
   own simulation results ("tried it; best redispatch left rho at 1.9").
6. Constraint twist: "substation 5 unavailable, crew on site" → agent finds
   the second-best action. (Shows judgment, not a lookup table.)

Visual: grid render goes red → green per step (plotly renders exist from
spike).

## 5. Success criteria

| Criterion | Bar |
|---|---|
| Rescue works | rho < 1.0 on demo scenario, live, end-to-end |
| Narration quality | judge can follow why each action was chosen |
| Honest benchmark | agent vs brute-force search vs do-nothing over N scenarios: success rate, actions taken, wallclock |
| Physics grounding | zero LLM-invented numbers; all values from Grid2Op/pandapower |
| Demo resilience | runs offline (local LLM), no API dependency, no network needed on stage |

## 6. Constraints & key decisions (already made)

- **24h timebox.** Demoable end-to-end slice beats polish. No speculative
  abstractions.
- **Environment: 118-bus primary, case14 fallback.** Live demo targets
  `l2rpn_neurips_2020_track2_small` (118 buses — a real-sized grid, not a
  toy; downloaded and local). The proven case14 arc stays runnable as the
  safety net: if the 118-bus re-spike stalls past a set cutoff, the demo
  ships on case14 and 118 becomes a benchmark slide. Decision reversed from
  the spike (which picked case14 for legibility) on the grounds that 14
  buses is too trivial for the hackathon; legibility is solved in the UI by
  zooming to the affected area (§10).
- **LLM:** local model via OpenAI-compatible server —
  `mlx-community/gemma-4-26B-A4B-it-qat-4bit` at `http://localhost:8003/v1`.
  Verified: native tool calling, multi-turn tool round-trips, ~77 tok/s.
  No Claude, no API cost, fully offline (a pitch point in itself).
- **Architecture scale:** ONE agent, ONE tool layer, 3-4 tools. Plain OpenAI
  tool-call loop (MCP dropped with the Claude pivot — no payoff, more moving
  parts).
- **Action search is a tool, not the LLM's job:** topology search feeds the
  agent ranked candidates; the local 4-bit model picks and justifies, it
  does not invent busbar arrays. (Grounding test showed it produces no-op
  assignments unaided.) At 118 buses the search tool takes a **scope**
  (substation subset): the agent reads where the overload sits and directs
  the search there — LLM-guided pruning of a space too big to brute-force
  blindly. Tool state summaries must stay compact (top-k loaded lines, not
  full 186-line dumps) to fit the local model's context.
- **Physics lever:** topology (bus-split) actions rescue the grid; redispatch
  alone barely helps on this case. Narration gotcha: bus assignment ≠ 0
  implicitly reconnects a disconnected line.
- **Real data role:** German TSO load curve (ENTSO-E API — same data the
  challenge's SMARD.de pointer refers to) is operating context only — real
  daily swing does NOT overload the grid; the N-1 event is the crisis. Do
  not oversell.

## 7. Out of scope (deliberate)

- RAG / retrieval infrastructure — 14-bus state fits in context; regulation
  excerpts are ~20 lines pasted into the system prompt.
- Multi-agent hierarchy / planning-coordination-action layers — overkill at
  this scale.
- Prompt-refinement machinery (judge/edit agents) — research, not a 24h
  feature.
- Real topology import (SimBench/PyPSA-Eur) — conversion risk, no judge
  payoff. Grid2Op's backend IS pandapower; the claim stands without it.
- Transient/dynamic stability — steady-state only, like all published
  systems. Roadmap slide material.
- Foundation-model screening (GridSFM_Open, challenge pointer) — even at 118
  buses the real solver screens all 186 N-1 cases in seconds, exactly. The
  surrogate pays off at **N-2** (~17k cases ≈ 9 min by solver, measured
  32 ms/solve — too slow inside "minutes to react"): screen
  with the model, verify the worst with the solver — Direction 4's own
  pattern. Roadmap slide material with concrete numbers; candidate stretch
  goal only if the core lands early. Caveat if used: these models break on
  unusual topologies, and bus-split actions create exactly that — never use
  it to evaluate our own fixes.
- ~~Multi-agent control~~ — **kept open** (see §6): start single-agent for
  the core loop; multi-agent split (e.g. screening agent + rescue agent, or
  per-area agents on a bigger grid) is a candidate extension if the core
  works early. MAPDN (challenge pointer) is the reference if we go there —
  note it is a voltage-control environment, adjacent to our thermal-overload
  problem, not the same task.
- Transformer-tap actions — narrated as part of the operator menu, but not
  implemented as an agent tool; topology actions are the proven lever on
  case14.

## 8. Why an LLM agent at all — the messiness thesis

On a clean, fully-specified problem, the brute-force baseline wins: it finds
the optimal action in seconds with a 100% success rate. Our own benchmark
will show this honestly. The agent's value begins exactly where the real
world stops being clean — and that argument must carry the pitch.

Messiness the agent handles and the optimizer cannot:

- **Natural-language operational constraints.** "Crew on site at substation
  5", "line 12 in maintenance until 14:00" — the agent maps operator language
  onto a pruned action space and finds the best *remaining* action. The
  baseline needs a programmer to re-encode its search space for every such
  sentence.
- **Conflicting objectives, justified in words.** Cheapest action vs fewest
  switching operations vs most margin restored. The agent weighs and
  *explains* the trade-off; an optimizer needs hand-tuned weights and emits
  a number.
- **Search pruning at scale — the headline number (measured).** The 118-bus
  grid has 72,107 unitary topology actions; at 32 ms per power flow, blind
  enumeration takes ~38 minutes. The operator has minutes. The agent reads
  the grid state, scopes the search to the substations around the overload
  (~35 actions, ~1 s), and the solver verifies only those. The solver alone
  is infeasible in operator time; the agent makes it tractable. (On case14
  this edge doesn't exist — 178 actions brute-force in seconds; it appears
  exactly when the grid gets real-sized.)
- **Regulatory context.** Narration framed against the N-1 principle and the
  15-minute N-0 restoration window — the language a control room actually
  speaks.
- **Real operating context.** ENTSO-E German load curve as the backdrop
  ("evening peak, demand still rising") — honest framing: context, not
  crisis.

Demo encodes this thesis as the constraint-twist beat (§4.6): same overload,
new sentence from the operator, different action chosen — and the agent says
why.

**Out of scope (state, don't build):** noisy measurements, load-forecast
uncertainty, communication failures. Roadmap material.

## 9. Simulation & scenarios

- **Time model: one-shot snapshot rescue.** Freeze the post-contingency
  state, search/simulate/apply, verify. No multi-step episodes, cooldowns, or
  Grid2Op opponent — spike only validated one-shot, and the demo doesn't need
  more. Benchmark wording must match ("per-scenario rescue", not "episode
  survival").
- **Scenario set:** all single-line N-1 outages on the 118-bus grid
  (186 lines) at a fixed load snapshot — measured: full screening in 6.1 s.
  This directly serves challenge objective #2 — *screen the what-ifs, solve
  only the dangerous ones*: screening table classifies all 186 outages
  harmless vs dangerous; agent rescues the dangerous ones. (Fallback: same
  structure on case14, 20 outages.) Stretch: repeat at 2-3 load levels from
  the ENTSO-E curve.
- **Snapshot selection matters:** the env's default first timestep is
  already stressed (max rho 1.30 before any event; 184/186 outages read
  "dangerous" against that baseline). The demo needs a healthy starting
  snapshot (scan chronics) and a danger definition relative to baseline,
  so the N-1 event — not the backdrop — is the crisis.
- **Safe-state definition:** primary bar is rho < 1.0 on all lines (N-0
  secure). Stretch claim: verify the *rescued* state is itself N-1 secure
  (re-run screening on the fixed grid) — only claim if checked.
- **Event trigger:** scripted scenario selection (operator picks a scenario,
  not free-form fault injection). Keeps the demo deterministic.

## 10. UI / demo surface

- **Form:** single local web page (extends the proven `workflow.html`
  pattern). Left: plotly grid render, red → green as actions land. Right:
  agent narration feed, chat-style. No build step, no framework, no Lovable —
  ingredients already exist in `artifacts/`.
- **118-bus legibility:** full-grid view only as overview (red lines visible
  at a glance); the working view zooms to the affected area — the overloaded
  lines plus their neighboring substations. Render legibility is an explicit
  re-spike checkpoint, not an afterthought.
- **Data flow:** agent loop writes one JSON/HTML artifact per step; page
  polls or is rebuilt per step. Dumb and reliable beats websockets at hour 20.
- **Driving the demo:** presenter selects scenario and sends the operator
  messages (including the constraint twist and the planted follow-up
  question) from a minimal input box. Scripted prompts kept in a crib sheet —
  nothing improvised on stage.
- **Resilience:** everything served from localhost; zero network dependencies
  on stage (matches §5 demo-resilience criterion).

## 11. Deliverables

1. **Working agent loop** (core): overloaded scenario → inspect → simulate →
   apply → safe, narrated. Reflection after apply (re-check rho, iterate).
2. **Screening table** (challenge objective #2): all 20 single-line outages
   classified safe/dangerous; agent rescues the dangerous ones.
3. **Benchmark table:** agent vs brute-force vs do-nothing over the scenario
   set — success rate, actions taken, wallclock.
4. **Demo UI:** local web page per §10 (grid render + narration feed +
   operator input).
5. **Demo assets:** per-step grid renders (red → green), constraint-twist
   scenario, planted follow-up question, presenter crib sheet.
6. **Pitch material:** positioning vs X-GridAgent, messiness thesis (§8),
   cost framing, regulation framing, roadmap slide.

## 12. Open items

- **Re-spike the rescue arc on the 118-bus env** (the pivot's main risk):
  ~~screening + search timing~~ DONE (6.1 s / 32 ms per solve / 72,107
  actions / scoped ≈ 1 s). Remaining: find a healthy starting snapshot in
  the chronics, pick a dangerous outage from it, and **verify a topology
  rescue exists** (the arc's keystone — unproven on 118). Set a go/no-go
  cutoff hour for falling back to case14.
- Verify 118-bus render legibility (zoomed affected-area view readable on a
  projector).
- Verify second-best action (constraint-twist beat) on whichever env the
  demo ships.
- Case14 fallback: the 20-outage screening + second-best check from the
  original plan still apply if the fallback triggers.
- Verify arXiv:2512.20789 resolves (needs browser outside sandbox).
- If citing X-GridAgent's 100%-success figure, attribute it as *their* result
  on *analysis* tasks — never as ours.
