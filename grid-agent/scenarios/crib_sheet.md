# Demo crib sheet - nothing improvised on stage

## Pre-flight

1. Model server up: `curl -s http://localhost:8003/v1/models`
2. `cd grid-agent && .venv/bin/python ui/serve.py` in terminal 1
3. `MPLCONFIGDIR=$TMPDIR/mpl .venv/bin/python -m agent.main --inbox` in terminal 2
4. Browser: `http://localhost:8000/ui/index.html`
5. Network off is fine for the demo path: model, UI, data, and Grid2Op are local.

## Script

1. Send: `Shift start. Please check the grid and secure it if needed.`

   Expect: inspect, scoped search over 88 of 72,107 actions, simulate, apply
   bus-split at substation 67. Crisis line is 177, between substations 115 and
   67, at rho about 1.30. Rescue brings max rho to about 0.80 and is stable for
   20 checked steps. Do-nothing blacks out after 4 steps.

2. Send: `Why not redispatch instead?`

   Expect: the agent says redispatch was not simulated in this run, then argues
   from the cost table and measured switching result. This is the honesty point:
   every rho value is in the tool feed, while redispatch is only a qualitative
   cost comparison.

3. Restart `agent.main`, then send:
   `Shift start. Please check the grid and secure it if needed. Substation 67 is unavailable, maintenance crew on site.`

   Expect: search includes `exclude_substations=[67]`, selects action `a-068-1`,
   a bus-split at substation 68. Verified result: simulated max rho 0.782,
   applied max rho 0.79, zero overloads, stable for 20 checked steps.

## If The Model Goes Off-Script

- Wrong numbers in narration: point at the tool feed; every number it may use is
  visible there. Restart the turn if needed.
- Search with an invalid substation: the tool now skips invalid IDs and reports
  them in `skipped_substations`.
- Total stall: restart `agent.main`; it reloads the crisis-at-open scenario.

## Numbers To Have In Your Head

- 118 buses, 186 lines.
- 72,107 topology actions total; blind brute force is quoted as about 38 minutes.
- Demo scope: 88 topology actions in about 3 seconds.
- Crisis: line 177, substations 115 to 67, rho about 1.30.
- Primary rescue: bus-split at substation 67, max rho about 0.80.
- Constraint rescue: exclude substation 67, bus-split at substation 68, max rho 0.79.
- Screening table: 186 outages, 26 dangerous relative to stressed baseline.
- Benchmark table: scoped brute force rescues the demo scenario and outage-line-183;
  the LLM agent rescues the demo scenario in the 5-row benchmark.
