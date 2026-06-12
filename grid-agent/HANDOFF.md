# Handoff — grid-agent next session

## Goal
Build the LLM agent loop (Claude + tools over Grid2Op) that rescues an
overloaded grid and narrates its reasoning — the core hackathon deliverable.

## Context

**Project:** Voltify — TUM.ai energy hackathon (Munich, June 12–13, 24h build
→ pitch). Team of two: energy expert + AI-agent software engineer. Chosen
challenge: **#5 Grid Operation Agents** (see `../CHALLENGES.md` for all six,
this folder's files for everything else).

**Repo:** https://github.com/dimitarvdenev/voltify (public, pushed, `main`).
Working dir: `grid-agent/` inside the repo.

**Spike done — all verified working:**
- Python env: `.venv` (Python 3.12 via uv — system 3.9 too old, brew 3.14 too
  new for wheels). `uv pip install --python .venv/bin/python -r requirements.txt`.
  Sandbox quirks: use `UV_CACHE_DIR=$TMPDIR/uv-cache`, `MPLCONFIGDIR=$TMPDIR/mpl`.
- `spike_overload_rescue.py` — proven demo arc on `l2rpn_case14_sandbox`:
  healthy (rho 0.92) → N-1 disconnect line 17 (4→5) → 4 lines overloaded
  (rho 1.91) → search 178 unitary topology actions via `obs.simulate()` →
  best bus-split at substation 5 → rho 0.83, zero overloads.
  Key physics: redispatch alone barely helps; topology (bus-split) actions are
  the lever. The fix also implicitly reconnects line 17 onto bus 2 (bus
  assignment ≠ 0 reconnects a line — narration gotcha).
- `spike_visualize.py`, `spike_plotly.py` — static PNGs + interactive plotly
  HTML renders in `artifacts/`.
- `spike_real_load_network.py` — real German load curve from ENTSO-E API
  (raw XML in `data/`, token in `.env` as `ENTSOE_TOKEN`, gitignored;
  `.env.example` committed). Honest finding: real daily swing (peak/mean
  1.12x) does NOT overload the grid — N-1 event is the crisis, real data is
  operating context only. Don't oversell in pitch.
- `workflow.html` — interactive walkthrough for the teammate: 4 tabs
  (healthy / overloaded / rescued / real DE load), plotly iframes. Serve via
  `python -m http.server` if file:// iframes blocked.
- `PRIOR_ART.md` — X-GridAgent paper analysis (arXiv:2512.20789, cited by the
  challenge). Headline: it ANALYZES, we OPERATE — they defer decision-making
  to future work, that's our lane. Contains 5 demo-polish ideas (regulation
  citations in prompt, cost-aware action ranking, live plot per step,
  follow-up Q&A from memory, roadmap framing) and a skip-list (no RAG, no
  multi-agent hierarchy, no prompt-refinement machinery — all overkill at
  14 buses).

**Key decisions made:**
- Stay on Grid2Op `l2rpn_case14_sandbox` for the live demo (14 buses =
  audience can see it; 118-bus combinatorics = one benchmark number on a
  slide, not a live render).
- Architecture: ONE agent + ONE MCP server with 3-4 tools
  (`get_grid_state`, `simulate_action`, `apply_action`, optionally
  `search_topology_actions`), following X-GridAgent's MCP-on-pandapower
  pattern. Reflection step after apply (re-check rho, iterate if needed).
- Baseline for benchmark slide: brute-force topology search (exists in spike)
  + do-nothing. Agent's edge: narration + pruned search + messy constraints
  (e.g. "substation 5 unavailable, crew on site" → agent finds second-best).
- Real topology swap (SimBench/PyPSA-Eur) rejected for 24h: conversion risk,
  no judge payoff. grid2op backend IS pandapower, claim stands.

## Blockers
- None technical. Two verify-before-pitch items: arXiv:2512.20789 link
  resolves (sandbox couldn't reach arxiv.org); don't present X-GridAgent's
  100%-success stat as ours.

## Expected Output
Working agent loop: scenario starts overloaded → Claude (via MCP tools)
inspects state, simulates candidates, applies fix, narrates each step in
operator language (cost + regulation framing per PRIOR_ART.md polish ideas).
Then: benchmark vs brute-force, demo polish, pitch material. Update README.md
architecture sketch as it firms up.
