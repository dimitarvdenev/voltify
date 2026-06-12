# AI Boom — Problems for Energy Suppliers

1. **Demand surge unpredictability** — data center load growth forecasts keep getting revised up; hard to plan grid capacity/generation investments years ahead.
2. **Grid connection queue backlog** — new data centers request huge capacity (100s of MW), queue times stretch years, suppliers can't build fast enough.
3. **Load concentration/locational stress** — hyperscalers cluster in specific regions (e.g. Northern Virginia, Ireland, parts of Germany), causing local grid congestion, transformer/substation upgrades needed.
4. **24/7 baseload requirement vs renewables intermittency** — AI workloads need constant power, conflicts w/ variable solar/wind, drives demand for gas peakers or nuclear/SMRs — tension w/ decarbonization goals.
5. **Price volatility/cost shifting** — large new demand can spike wholesale prices, costs sometimes socialized to residential customers (rate cases).
6. **Water/cooling strain** — secondary issue but linked to power infrastructure siting decisions.
7. **Long lead times mismatch** — AI/data center buildout (months) vs power plant/transmission buildout (years) — chronic supply-demand timing gap.
8. **Stranded asset risk** — if AI demand growth slows/shifts (efficiency gains, model optimization), suppliers who overbuilt face stranded capacity.

## Related hackathon ideas (from IDEAS.md)
- 1 — AI grid congestion forecaster
- 6 — Grid-edge anomaly detector
- 40 — Real-time carbon intensity router for data center workloads

## Solutions per problem (root-cause level)

1. **Demand surge unpredictability** → AI compute becomes fully interruptible/shiftable load. Workloads self-schedule around grid signals, forecasting accuracy stops mattering.
2. **Grid connection queue backlog** → Data centers bring own on-site generation + storage (gas, SMRs, solar+battery), behind-the-meter. No grid connection request, no queue.
3. **Load concentration/locational stress** → Compute follows power, not power follows compute — workloads dynamically migrate across data centers to wherever grid headroom exists.
4. **24/7 baseload vs renewables intermittency** → Decouple training/inference timing from continuous power — run heavy compute only during renewable surplus windows.
5. **Price volatility/cost shifting** → Direct PPAs / dedicated tariffs reflecting true marginal cost, isolated from residential rate pool. Cost-causation pricing.
6. **Water/cooling strain** → Closed-loop liquid immersion cooling, zero water consumption.
7. **Long lead times mismatch** → Modular, factory-built power (containerized gas turbines, BESS, SMRs) with manufacturing timelines matching data center construction.
8. **Stranded asset risk** → Only build modular/relocatable/repurposable capacity. If demand shifts, assets move or get redeployed.

Common thread: flexibility (in compute, generation, or siting) eliminates each problem at its root rather than mitigating it.

## Tech stack per solution (24h hackathon, software-only)

**1. Flexible AI compute load**
- Backend: Python/FastAPI, simple job queue (Redis/Celery or in-memory)
- Data: ElectricityMaps or ENTSO-E API (grid carbon/price signals)
- Logic: scheduler delays/runs jobs based on signal threshold
- Frontend: React (Lovable) dashboard — queue status, signal chart

**2. Behind-the-meter generation (on-site gen + storage)**
- Backend: Python optimization (PuLP/scipy) — dispatch optimizer (solar+battery+gas vs grid draw)
- Data: synthetic/historical solar + load profiles
- Frontend: React dashboard, recharts showing dispatch mix over time
- Optional: LLM explains dispatch decisions in plain language

**3. Compute-follows-power (geo-distributed scheduling)**
- Backend: FastAPI, routing algorithm (pick region w/ best price/carbon)
- Data: multi-region grid data (ElectricityMaps)
- Frontend: map viz (Mapbox GL / deck.gl) — workload migration live
- ⚡ VR option: "globe room," stand inside 3D map watching workloads hop between regions

**4. Decouple compute timing from baseload**
- Same stack as #1 — scheduler + forecast
- Add: simple forecasting model (linear regression / Prophet) on renewable output
- Frontend: timeline view — "run now" vs "queued" jobs vs renewable curve

**5. Direct PPA / cost-causation pricing**
- Backend: rule-based pricing engine (FastAPI)
- Data: wholesale price API (EPEX/ENTSO-E) + synthetic contract terms
- Frontend: compare "socialized cost" vs "direct PPA" billing for data center vs residential
- Optional: LLM-generated contract summary/explainer

**6. Immersion cooling (visualization/digital twin angle)**
- Hardware-heavy — software angle = simulation/visualization only
- ⚡ VR/WebXR (Three.js + react-three-fiber) — 3D data center model, toggle air vs immersion cooling, show PUE/water savings
- Backend: simple calculator (Python) for energy/water savings numbers

**7. Modular factory-built power (planning tool)**
- Backend: simulation — capacity vs demand growth curves over time (Python/numpy)
- Frontend: slider for "modular vs traditional" build timeline, chart showing gap closing
- Optional: LLM agent suggests optimal mix of modular units to meet projected demand
- ⚡ VR option: site visualization, place modular units (containers) in 3D space, see capacity grow over time

**8. Modular/relocatable assets (no stranded risk)**
- Backend: portfolio optimizer — simulate asset redeployment given demand scenarios
- Frontend: asset map + utilization over time, "redeploy" animation
- Optional: LLM agent recommends redeployment when utilization drops below threshold

## Common stack across all (recommended baseline)
- Frontend: React + Vite + Tailwind + shadcn (Lovable-compatible)
- Backend: Python FastAPI
- AI: Anthropic API (Sonnet 4.6) for copilot/explainer/agent features — use `claude-api` skill, include prompt caching
- VR (if used): WebXR + react-three-fiber/Three.js, runs in browser, works w/ provided headsets
- Charts: recharts

## Data APIs

- **ENTSO-E Transparency Platform** (transparency.entsoe.eu)
  - EU grid operator data: generation by source, load, cross-border flows, day-ahead prices, congestion
  - Free, needs API token (register email, get key same day)
  - REST/XML API — Python wrapper `entsoe-py` helps

- **ElectricityMaps API** (electricitymaps.com)
  - Real-time + historical carbon intensity, power breakdown by country/region
  - Free tier exists (rate-limited), needs API key signup
  - Cleaner JSON than ENTSO-E, good for carbon-aware routing demos

- **Open-Meteo** (open-meteo.com)
  - Weather forecast + historical (solar irradiance, wind speed, temp)
  - No API key needed, free, JSON
  - Good for solar/wind generation estimates

- **EPEX Spot / Day-ahead prices**
  - Often bundled in ENTSO-E data (price section) — avoids separate signup

## Maps

- **Mapbox GL JS**
  - Vector maps, custom styling, good for animated markers/routes
  - Free tier: 50k loads/month, needs API key
  - React wrapper: `react-map-gl`

- **deck.gl**
  - WebGL layers on top of maps (arcs, heatmaps, 3D extrusions) — good for flow visualizations
  - Works with Mapbox or standalone, pairs well w/ React

- **Leaflet**
  - Lighter alternative, no API key needed (OpenStreetMap tiles), simpler but less flashy

For hackathon: Mapbox + deck.gl for polished animated visuals; Leaflet for zero-config speed.
