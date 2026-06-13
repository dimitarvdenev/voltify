# The Problem We're Solving (plain-language version)

*Written for the whole team — no power-systems or AI background assumed.*

## The grid must always survive one failure

Picture the power grid as a road network for electricity: power flows from
generators (power plants, wind farms) to consumers over transmission lines.
The golden rule of grid operation is called **N-1 security**: at any moment,
the grid must be able to lose any *one* line or power plant — a storm takes
down a cable, a transformer fails — without anything else breaking.

## Why one failure can snowball

Electricity doesn't take orders — it flows wherever physics sends it. When a
line dies, its power instantly reroutes over neighboring lines. If those were
already busy, they're now **overloaded** — carrying more than they're rated
for. Overloaded lines overheat, and protection systems switch them off to
save the hardware. But each line that switches off pushes its load onto the
next ones. That chain reaction is how big blackouts happen (Italy 2003,
large parts of Europe 2006).

## The human in the control room has minutes

When an overload appears, an operator must act before the chain reaction
starts. Their options:

- **re-route power** by flipping switches in substations (essentially free),
- **redispatch** — tell power plants to produce more or less (costs real
  money),
- **curtail** — as a last resort, cut consumers or renewables off (very
  expensive, regulatory consequences).

Choosing well takes deep experience — and those experts are scarce, while
the grid gets more stressful every year: more renewables, more volatility,
more AI data centers.

## The trap: the best move is cheap, but almost impossible to find fast

Often the smartest action costs nothing — flipping a few switches in one
substation re-routes the flows and the overload vanishes. But on a
realistically-sized grid (we use one with 118 substations), there are
**72,000+ possible switch combinations**. We measured it: checking each one
with the physics simulation takes about **38 minutes**. The operator has
maybe five. The exact tools are too slow; the fast judgment lives only in a
veteran operator's head.

## What we're building

An AI agent that works like the veteran:

1. **Looks** at the grid and sees where the trouble is.
2. **Narrows down** — out of 72,000 options, it reasons "the overload sits
   between substations 34 and 36, the fix is somewhere near there" and
   selects ~35 candidates. That takes about a second.
3. **Verifies** — each candidate is checked by a real physics simulation.
   The AI never guesses the physics; every number comes from the same kind
   of engine grid operators already trust.
4. **Explains** — in operator language: *"Line 34–36 is at 177% of its
   limit. Splitting the busbar in substation 34 reroutes the flow; loading
   drops to 83%. Cost: zero — it's just switching. The alternative,
   redispatch, would cost ~€4k."*

That last part is the point. Research systems based on reinforcement
learning can operate grids but are black boxes — no control room will trust
them. Analysis tools can explain the grid but don't act. **Ours acts *and*
explains.**

## The demo

A healthy grid loses a line. Four lines go red. The agent investigates,
fixes the problem with a zero-cost switching action, and narrates every
step. Then we tell it: *"you can't use that substation — repair crew is on
site."* It finds the next-best fix. Like a real colleague would.

---

*Status note: the speed numbers (38 min blind search vs ~1 s agent-scoped,
32 ms per power flow, 186-outage screening in 6.1 s) are measured on the
118-bus environment. Still to prove on 118 buses: that a switching fix
actually rescues a dangerous outage end-to-end — that verification is the
next task. The full product requirements live in `PRD.md`.*
