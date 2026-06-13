# PRD — Grid Operation Agent (Voltify)

Consolidated from the official E.ON challenge text (**Direction 1: Grid
Operation Agents** — note: `../CHALLENGES.md` is an earlier draft with
different numbering), `docs/HANDOFF.md`, `docs/PRIOR_ART.md`, `README.md`, and the
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

**Verified on the 118-bus env (crisis-at-open shape — the env begins inside
the emergency, no injected outage needed):**

1. Grid opens in crisis: line 177 (substations 115→67) at 130% loading.
2. Do-nothing baseline: **blackout in 4 steps** (measured — protection trips
   cascade). The countdown is real, not staged.
3. Agent inspects state, scopes the search to the 5 substations around the
   overload (88 candidate actions out of 72,107 total, ~3 s), simulates,
   picks a bus-split at substation 67, applies it → max rho 0.80, stable
   for 20+ further steps (verified with real env.step, not just simulate).

4. Agent narrates each step: which limit is violated, what it tried, why the
   chosen action wins across the full operator menu — switching ≈ free,
   redispatch priced per MW, curtailment expensive + regulatory pain,
   transformer taps noted where relevant — and which rule requires acting
   (N-1 principle, thermal limits).
5. Operator asks a follow-up ("why not redispatch?") — agent answers from its
   own simulation results, quoting the numbers it measured during the run
   (case14 precedent: best redispatch left rho at 1.9; the 118-bus
   equivalent comes out of the agent's own simulations).
6. Constraint twist: "substation 67 unavailable, crew on site" → agent finds
   the second-best action. (Shows judgment, not a lookup table. Second-best
   existence on 118 is an open verification item, §13.)

*(Historical: the case14 spike arc — healthy 0.92 → N-1 line loss → rho
1.91 → bus-split → 0.83 — stays in the repo as reference, not a demo path.)*

Visual: grid render goes red → green per step (plotly renders exist from
spike).

## 5. Success criteria

| Criterion | Bar |
|---|---|
| Rescue works | rho < 1.0 on demo scenario, live, end-to-end |
| Narration quality | judge can follow why each action was chosen |
| Honest benchmark | agent vs scoped brute-force vs do-nothing over N scenarios: success rate, actions taken, wallclock |
| Physics grounding | zero LLM-invented numbers; all values from Grid2Op/pandapower |
| Demo resilience | runs offline (local LLM), no API dependency, no network needed on stage |

## 6. Constraints & key decisions (already made)

- **24h timebox.** Demoable end-to-end slice beats polish. No speculative
  abstractions.
- **Environment: 118-bus, no fallback.** Live demo runs on
  `l2rpn_neurips_2020_track2_small` (118 buses — a real-sized grid, not a
  toy; downloaded, local, keystone-proven §13). Decision reversed from the
  spike (which picked case14 for legibility) on the grounds that 14 buses
  is too trivial for the hackathon; legibility is solved in the UI by
  zooming to the affected area (§10). **118 or bust** — team decision; the
  case14 spike scripts remain in the repo as reference but are not a demo
  path.
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
- **Search pruning at scale — the headline number (measured, proven on the
  demo scenario).** The 118-bus grid has 72,107 unitary topology actions; at
  32 ms per power flow, blind enumeration takes ~38 minutes. The operator
  has minutes. The agent reads the grid state, scopes the search to the 5
  substations around the overload (88 actions, 3 s), and the solver verifies
  only those — that exact scoped search found the proven rescue
  (`scenarios/arc_118.json`). The solver alone is infeasible in operator
  time; the agent makes it tractable. (On case14 this edge doesn't exist —
  178 actions brute-force in seconds; it appears exactly when the grid gets
  real-sized.)
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
  harmless vs dangerous; agent rescues the dangerous ones. Stretch: repeat
  at 2-3 load levels from the ENTSO-E curve.
- **Crisis-at-open (verified):** every chronic in this env starts stressed
  (line 177 at rho ~1.30 across all 20 chronics; healthy snapshots do not
  exist at t0, and do-nothing reaches game-over at step 4). The demo
  embraces this: the env opens inside the emergency, and "do nothing =
  blackout in 4 steps" is the measured baseline. Screening-table danger
  definitions must be read relative to that stressed baseline (a naive
  rho>1 cutoff marks 184/186 outages dangerous).
- **Safe-state definition:** primary bar is rho < 1.0 on all lines (N-0
  secure). Stretch claim: verify the *rescued* state is itself N-1 secure
  (re-run screening on the fixed grid) — only claim if checked.
- **Event trigger:** scripted scenario selection (operator picks a scenario,
  not free-form fault injection). Keeps the demo deterministic.

## 10. UI / demo surface

- **Form:** single local web page (extends the proven `artifacts/workflow.html`
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
2. **Screening table** (challenge objective #2): all 186 single-line outages
   on the 118-bus grid classified safe/dangerous relative to the stressed
   baseline (§9); agent rescues the dangerous ones.
3. **Benchmark table:** agent vs **scoped** brute-force vs do-nothing over
   the scenario set — success rate, actions taken, wallclock. (Blind
   brute-force at 38 min/scenario is quoted as a number, not run per
   scenario.)
4. **Demo UI:** local web page per §10 (grid render + narration feed +
   operator input).
5. **Demo assets:** per-step grid renders (red → green), constraint-twist
   scenario, planted follow-up question, presenter crib sheet.
6. **Pitch material:** positioning vs X-GridAgent, messiness thesis (§8),
   cost framing, regulation framing, roadmap slide.

## 12. Team split

- **Engineer (Dimitar):** agent loop, tool layer, UI, benchmark + screening
  runs — deliverables 1-4 of §11.
- **Energy expert (teammate):** scenario vetting, cost constants, regulation
  excerpt for the system prompt, narration quality review (does it sound
  like an operator?), presenter crib sheet, pitch — deliverables 5-6 of §11.

## 13. Open items

- ~~Re-spike the rescue arc on the 118-bus env~~ **DONE — GO.** Keystone
  proven (`scenarios/arc_118.json`): env opens in crisis (line 177 at 1.30,
  do-nothing blackout at step 4), scoped search 88/72,107 actions in 3 s,
  bus-split at sub 67 → rho 0.80, stable 20+ steps after real apply. Note
  the arc shape changed: crisis-at-open, no injected outage (all 20 chronics
  start stressed; healthy snapshots don't exist in this env's design).
- **Constraint-twist second-best on 118:** with substation 67 excluded, does
  another scoped substation (64/68/80/115) still rescue? Same check as the
  old case14 second-best item, now on the proven scenario.
- Verify 118-bus render legibility (zoomed affected-area view readable on a
  projector).
- Verify arXiv:2512.20789 resolves (needs browser outside sandbox).
- If citing X-GridAgent's 100%-success figure, attribute it as *their* result
  on *analysis* tasks — never as ours.
