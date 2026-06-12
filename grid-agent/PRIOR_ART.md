# Prior Art: X-GridAgent — What It Means for Our Plan

Paper: *X-GridAgent: An LLM-Powered Agentic AI System for Assisting Power Grid
Analysis* (Wen & Chen, Texas A&M, arXiv:2512.20789). Referenced directly by the
challenge description as a repo to study.

## The headline: it analyzes, we operate

X-GridAgent is a natural-language **analysis assistant** over pandapower: run
power flow, find loaded lines, run N-1 contingency, report violations. It never
**fixes** anything — no remediation, no action selection, no safe-state
recovery. The paper's own conclusion defers "advanced decision-making
functionalities" to future work.

Our agent closes exactly that loop: overload → search actions → simulate →
apply → grid safe, with narrated reasoning.

**Pitch line:** "X-GridAgent answers questions about the grid. Ours operates it."

## Points that strengthen our plan

1. **MCP tool servers on pandapower are validated prior art.** The paper builds
   8 MCP servers over pandapower as its core architecture. Our planned MCP
   server (`get_grid_state`, `simulate_action`, `apply_action`,
   `search_topology_actions`) follows the same proven pattern — we cite the
   paper and position ourselves as adding the action layer it defers.

2. **Physics-grounding is the established norm.** All numerical results come
   from domain solvers, never from the LLM. Our design already does this by
   construction (Grid2Op/pandapower computes everything; agent only picks
   actions). We can claim the norm with a straight face.

3. **Reflection loop is cheap and credible.** Their action layer re-checks
   after each tool call whether the task is done and iterates if not. For us:
   after `apply_action`, agent re-reads rho, decides done or continue. Trivial
   to implement, matches published practice.

4. **Their evaluation discipline is copyable.** They verify outputs against
   manually-computed ground truth and run each query 30× (temperature 0),
   reporting success rate. Our benchmark slide does the same: agent vs
   brute-force baseline over N scenarios, success rate + actions taken +
   wallclock.

5. **The field is crowded with analysis agents, not operators.** Their
   related-work survey (GridMind, PowerChain, Grid-Agent, DrAgent...) is all
   Q&A/analysis or single-task systems. Operational rescue + narration +
   honest baseline on Grid2Op remains the open lane. The closest prior art for
   *operation* is L2RPN RL agents — black boxes with no explanation, which our
   explainability angle directly beats.

## What we deliberately skip (and why)

- **Prompt refinement with judge/edit agents** — research contribution, not a
  24h feature. Hand-written system prompt suffices at our scale.
- **Schema-adaptive hybrid RAG** — solves retrieval over 2k-bus result tables.
  Our 14-bus state fits directly in the context window; no RAG needed.
- **8 servers / 3-layer planning-coordination-action hierarchy** — justified at
  their task breadth, overkill for one rescue workflow. Single agent + one MCP
  server with 3-4 tools.

## Demo-polish ideas mined from the paper

Ranked by payoff/effort. All fit in the agent prompt + 1-2 extra tools; zero
new infrastructure.

1. **Regulation-grounded narration** (from their Retrieval server, Q2/Q11).
   They cite ERCOT operating guides with section numbers. Ours: paste a short
   excerpt of ENTSO-E Operation Handbook / German grid code rules (N-1
   principle, thermal limits, voltage bands) into the system prompt. Agent
   narrates: "line 8-9 at 191% violates the continuous thermal limit; the
   operating handbook requires return to an N-0 secure state within 15 min."
   ~20 lines of prompt text, no RAG needed at 14 buses.

2. **Cost-aware action ranking** (their OPF cost focus + challenge's
   "low-cost actions"). Tag each action type with a cost: bus split ≈ free
   (switch operation), redispatch priced per MW, curtailment expensive +
   regulatory pain. Agent justifies: "choosing topology fix: zero cost vs
   ~€4k redispatch." Three hand-coded cost constants.

3. **Live plot after each agent step** (their Plot server). Agent tool
   `render_grid` emits a plotly HTML/PNG per step — demo shows the grid going
   red → green as the narration streams. Render code already exists in the
   spikes; just wire it as a tool.

4. **Follow-up Q&A via short-term memory** (their coordination-layer memory).
   After the rescue, operator asks "why not redispatch?" — agent answers from
   stored simulation results ("simulated it; best redispatch left rho at
   1.9"). The numbers already exist. Plant one such question in the demo.

5. **Roadmap framing from their future work.** They defer dynamic/transient
   studies — so does everyone. Roadmap slide: "steady-state today (like all
   published systems), transient stability next." Signals we know the
   field's edge without building anything.

## Verify before pitch

- arXiv:2512.20789 link resolves (could not check from sandbox).
- If citing their numbers (100% success over 30 runs), cite as *their* result
  on *analysis* tasks, not ours.
