# Energy x AI Hackathon — Challenges

## 1. Invertix: Data-Center Siting & Power
**Core Problem:** Data center siting involves complex trade-offs between electricity price, carbon footprint, grid congestion, and connectivity.

**Objectives:**
- Recommend locations for specific data-center sizes and explain trade-offs.
- Plan a supply mix (grid, PPA, on-site generation) optimized for cost and carbon.
- Overlay capacity, prices, carbon, and congestion to identify optimal vs. poor sites.

**Data:** PyPSA-Eur, Ember data, OpenStreetMap, IEA Energy & AI.
**Tech/Models:** Not specified — focus on reasoning and optimization.

## 2. Satellite Data for Solar
**Core Problem:** Turning raw satellite feeds (irradiance, cloud cover, atmospheric conditions) into operational outputs that operators can use.

**Objectives:**
- Develop a generation forecast that outperforms persistence models using satellite-derived irradiance.
- Create a "nowcast" for intraday trading or grid balancing decisions.
- Build any tool that converts raw satellite data into operational intelligence.

**Data:** Copernicus / Sentinel, NASA POWER, EU METEASAT, Google Earth Engine.
**Tech/Models:** Not specified — focus on converting raw feeds into operational outputs.

## 3. Digital Twins of Solar Plants
**Core Problem:** Moving beyond the standard Performance Ratio (PR) to find hidden underperformance and financial impacts from quality issues, downtime, and grid curtailments using 10 years of monitoring data.

**Objectives:**
- Build per-inverter ML power models (including current and voltage).
- Benchmark individual inverter models against a 10-year real-world dataset.
- Compare results across different module types over long timelines.

**Data:** 10 years of real solar plant monitoring data (inverter-level, current, voltage).
**Tech/Models:** `pvlib-python`, `scikit-learn`, `LightGBM`.

## 4. Built Useful Agents for the Provided Dataset
**Core Problem:** Transforming raw plant data (minute-resolution telemetry, error codes, service tickets, design info) into tools for Operations & Maintenance (O&M) teams.

**Objectives:**
- Develop inverter failure detection systems.
- Link error code events to their specific impact on inverter production.
- Create chatbots capable of providing answers and visualizations based on monitoring data.

**Data:** 10 years of real solar plant monitoring/operational data from two utility-scale PV plants (minute-resolution inverter telemetry, error codes, service tickets, plant design info).
**Tech/Models:** `IEC 61724`, `PVsyst`, `pvlib`, `DuckDB`, `LangGraph`.

## 5. Grid Operation Agents
**Core Problem:** Helping operators manage "N-1 security" (ensuring the grid survives the loss of any single line or generator) by proposing safe, low-cost actions during real-time events.

**Objectives:**
- Develop agents that can return an overloaded grid to a safe state while narrating their reasoning.
- Screen thousands of "what if" failure scenarios to identify and solve only the dangerous ones.
- Benchmark LLM agents against rule-based or optimization baselines.

**Data:** Not specified — focus on "what if" failure scenarios.
**Tech/Models:** `pandapower`, `Grid2Op`, `L2RPN`, `PyPSA-Eur`.

## 6. Grid Foundation Models
**Core Problem:** Leveraging pretrained grid models (which predict powerflow dispatch much faster than traditional solvers) to enable near-instantaneous decision-making.

**Objectives:**
- Create interactive "what-if" explorers (e.g., "drag a load, see the grid respond").
- Rank risky failure cases and verify them with real solvers.
- Conduct honest evaluations of model accuracy and identify where the model breaks.

**Data:** `GridSFM_Open`, `OPFData`.
**Tech/Models:** `pandapower`, `gridfm-graphkit`.
