# Grid Operation Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the LLM agent that rescues the overloaded 118-bus grid and narrates its reasoning, per `SPEC.md`.

**Architecture:** One Python process: a 4-tool layer (`GridTools`) over Grid2Op with a server-side action registry, driven by a plain OpenAI tool-call loop against the local model at `localhost:8003/v1`. A static UI polls per-step JSON artifacts; bench scripts produce the screening and benchmark tables.

**Tech Stack:** Python 3.12 (`.venv`), Grid2Op (`l2rpn_neurips_2020_track2_small`, local data in `data_grid2op/`), `openai` client, plotly (`grid2op.PlotGrid.PlotPlotly`), pytest, stdlib `http.server`.

**Working directory for ALL commands:** `grid-agent/` (repo root is one level up). All tests run as `.venv/bin/python -m pytest tests/ -v` from `grid-agent/` so the `agent` package is importable from cwd.

**Environment quirks (from HANDOFF.md):** install with `UV_CACHE_DIR=$TMPDIR/uv-cache uv pip install --python .venv/bin/python -r requirements.txt`; matplotlib wants `MPLCONFIGDIR=$TMPDIR/mpl`. Keep `numpy<2`.

**Ground truth:** every solver-dependent assertion uses `scenarios/arc_118.json` (chronic 0 opens in crisis: line 177 at rho 1.30; scoped search over subs [64, 67, 68, 80, 115] finds bus-split at sub 67 → rho 0.796 simulated / 0.806 applied; 20+ stable steps). Use tolerances (`abs=0.05`), not exact floats — solver/version drift must not break tests.

---

### Task 1: Scaffolding — package, config, test fixtures

**Files:**
- Modify: `requirements.txt`
- Create: `agent/__init__.py`
- Create: `agent/config.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Add new dependencies**

Replace `requirements.txt` content with:

```
grid2op
pandapower
numpy<2
matplotlib
plotly
openai
pytest
```

- [ ] **Step 2: Install**

Run: `UV_CACHE_DIR=$TMPDIR/uv-cache uv pip install --python .venv/bin/python -r requirements.txt`
Expected: resolves and installs `openai`, `pytest` (plotly likely already present from spike).

- [ ] **Step 3: Create package and config**

`agent/__init__.py` — empty file.

`agent/config.py`:

```python
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

LLM_BASE_URL = "http://localhost:8003/v1"
LLM_MODEL = "mlx-community/gemma-4-26B-A4B-it-qat-4bit"
ENV_NAME = "l2rpn_neurips_2020_track2_small"
GRID2OP_LOCAL_DIR = os.path.join(ROOT, "data_grid2op")
DEMO_CHRONIC_IDX = 0

MAX_ACTIONS_PER_SUB = 600     # sub 48 alone has ~65k combos — never search it
TOP_K_CANDIDATES = 5
TOP_K_LOADED_LINES = 5
MAX_LOOP_ITERATIONS = 12
MAX_APPLY_ATTEMPTS = 2
STABILITY_CHECK_STEPS = 20
MAX_TOOL_RESULT_CHARS = 1500

RUN_DIR = os.path.join(ROOT, "artifacts", "run")
RENDER_DIR = os.path.join(RUN_DIR, "renders")
```

- [ ] **Step 4: Create test fixtures**

`tests/__init__.py` — empty file.

`tests/conftest.py`:

```python
import json
import os

import pytest

from agent import config


@pytest.fixture(scope="session")
def arc():
    with open(os.path.join(config.ROOT, "scenarios", "arc_118.json")) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def tools():
    """Session-scoped GridTools on the demo chronic. Read-only tests share it;
    tests that mutate the env (apply_action) must build their own instance."""
    from agent.tools import GridTools
    return GridTools()
```

- [ ] **Step 5: Verify pytest collects (no tests yet)**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: `no tests ran` (exit code 5 is fine), no import errors.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt agent/__init__.py agent/config.py tests/__init__.py tests/conftest.py
git commit -m "feat: scaffold agent package, config, test fixtures"
```

---

### Task 2: `GridTools.get_grid_state`

**Files:**
- Create: `agent/tools.py`
- Create: `tests/test_tools.py`

- [ ] **Step 1: Write the failing test**

`tests/test_tools.py`:

```python
import pytest


def test_get_grid_state_reports_crisis(tools, arc):
    state = tools.get_grid_state()
    assert state["max_rho"] == pytest.approx(arc["crisis_max_rho"], abs=0.05)
    assert state["n_overloaded"] >= 1
    overloaded_ids = [l["line_id"] for l in state["overloaded_lines"]]
    assert arc["crisis_line_id"] in overloaded_ids
    crisis = next(l for l in state["overloaded_lines"]
                  if l["line_id"] == arc["crisis_line_id"])
    assert {crisis["from_sub"], crisis["to_sub"]} == set(arc["crisis_line_subs"])
    assert len(state["top_loaded_lines"]) <= 5
    # 1-hop scope hint must contain the proven rescue neighborhood
    assert set(arc["scoped_subs"]) <= set(state["candidate_scope_subs"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.tools'`

- [ ] **Step 3: Implement `GridTools` with `get_grid_state`**

`agent/tools.py`:

```python
"""Tool layer: Grid2Op env + server-side action registry.

The LLM never constructs actions. search_topology_actions enumerates and
simulates candidates, stores the Grid2Op action objects in self.registry,
and returns ids + solver summaries. simulate/apply take an action_id.
"""
import time

import grid2op
import numpy as np

from agent import config

grid2op.change_local_dir(config.GRID2OP_LOCAL_DIR)


class GridTools:
    def __init__(self, env_name=config.ENV_NAME,
                 chronic_idx=config.DEMO_CHRONIC_IDX):
        self.env = grid2op.make(env_name)
        self.env.set_id(chronic_idx)
        self.obs = self.env.reset()
        self.registry = {}      # action_id -> grid2op action object
        self.meta = {}          # action_id -> summary dict (for narration)
        self.done = False

    # ---------- helpers ----------

    def _line_summary(self, line_id):
        return {
            "line_id": int(line_id),
            "from_sub": int(self.obs.line_or_to_subid[line_id]),
            "to_sub": int(self.obs.line_ex_to_subid[line_id]),
            "rho": round(float(self.obs.rho[line_id]), 3),
        }

    def _scoped_subs(self, n_hops=1):
        """Substations at endpoints of overloaded lines, grown n_hops."""
        over = np.where(self.obs.rho > 1.0)[0]
        subs = set()
        for line_id in over:
            subs.add(int(self.obs.line_or_to_subid[line_id]))
            subs.add(int(self.obs.line_ex_to_subid[line_id]))
        for _ in range(n_hops):
            grown = set(subs)
            for line_id in range(self.env.n_line):
                a = int(self.obs.line_or_to_subid[line_id])
                b = int(self.obs.line_ex_to_subid[line_id])
                if a in subs:
                    grown.add(b)
                if b in subs:
                    grown.add(a)
            subs = grown
        return sorted(subs)

    # ---------- tools ----------

    def get_grid_state(self):
        rho = self.obs.rho
        overloaded = np.where(rho > 1.0)[0]
        top = np.argsort(-rho)[:config.TOP_K_LOADED_LINES]
        return {
            "max_rho": round(float(rho.max()), 3),
            "n_overloaded": int(len(overloaded)),
            "overloaded_lines": [self._line_summary(l) for l in overloaded],
            "top_loaded_lines": [self._line_summary(l) for l in top],
            "disconnected_lines": [int(l) for l in
                                   np.where(~self.obs.line_status)[0]],
            "candidate_scope_subs": self._scoped_subs(n_hops=1),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_tools.py -v`
Expected: PASS (env load takes a few seconds on first fixture use).

- [ ] **Step 5: Commit**

```bash
git add agent/tools.py tests/test_tools.py
git commit -m "feat: GridTools.get_grid_state with scope hint"
```

---

### Task 3: `GridTools.search_topology_actions`

**Files:**
- Modify: `agent/tools.py`
- Modify: `tests/test_tools.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tools.py`:

```python
def test_search_finds_proven_rescue(tools, arc):
    res = tools.search_topology_actions(arc["scoped_subs"])
    assert res["actions_simulated"] > 50          # arc measured 88
    assert res["actions_total_grid"] > 70000      # arc measured 72107
    assert 1 <= len(res["candidates"]) <= 5
    best = res["candidates"][0]
    assert best["substation"] == arc["rescue_substation"]
    assert best["simulated_max_rho"] == pytest.approx(
        arc["rescued_max_rho_simulated"], abs=0.05)
    assert best["simulated_max_rho"] < 1.0
    assert best["action_id"] in tools.registry
    assert best["cost_class"].startswith("switching")


def test_search_respects_exclusions(tools, arc):
    res = tools.search_topology_actions(
        arc["scoped_subs"], exclude_substations=[arc["rescue_substation"]])
    assert all(c["substation"] != arc["rescue_substation"]
               for c in res["candidates"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_tools.py -v`
Expected: 2 new FAILs — `AttributeError: ... no attribute 'search_topology_actions'`

- [ ] **Step 3: Implement search + registry**

Append to the `GridTools` class in `agent/tools.py`:

```python
    def _action_effects(self, act, sim_obs):
        """Lines reconnected and switching-op count for one candidate."""
        reconnects = [int(l) for l in range(self.env.n_line)
                      if not self.obs.line_status[l] and sim_obs.line_status[l]]
        set_bus = act.set_bus
        switching_ops = int(np.sum(
            (set_bus != 0) & (set_bus != self.obs.topo_vect)))
        return reconnects, switching_ops

    def search_topology_actions(self, substations, exclude_substations=None):
        excluded = set(exclude_substations or [])
        subs = [int(s) for s in substations if int(s) not in excluded]
        t0 = time.time()
        results, skipped, n_tried = [], [], 0
        for sub_id in subs:
            acts = self.env.action_space.get_all_unitary_topologies_set(
                self.env.action_space, sub_id=sub_id)
            if len(acts) > config.MAX_ACTIONS_PER_SUB:
                skipped.append({"sub": sub_id,
                                "reason": f"{len(acts)} combos, over cap"})
                continue
            for i, act in enumerate(acts):
                sim_obs, _, sim_done, _ = self.obs.simulate(act)
                n_tried += 1
                if sim_done:
                    continue
                action_id = f"a-{sub_id:03d}-{i}"
                reconnects, n_ops = self._action_effects(act, sim_obs)
                self.registry[action_id] = act
                self.meta[action_id] = {
                    "action_id": action_id,
                    "substation": sub_id,
                    "description": f"bus-split at substation {sub_id}",
                    "simulated_max_rho": round(float(sim_obs.rho.max()), 3),
                    "simulated_n_overloaded": int((sim_obs.rho > 1.0).sum()),
                    "reconnects_lines": reconnects,
                    "switching_ops": n_ops,
                    "cost_class": "switching (~free)",
                }
                results.append(self.meta[action_id])
        results.sort(key=lambda r: r["simulated_max_rho"])
        return {
            "actions_simulated": n_tried,
            "actions_total_grid": self._total_unitary_actions(),
            "search_seconds": round(time.time() - t0, 1),
            "skipped_substations": skipped,
            "candidates": results[:config.TOP_K_CANDIDATES],
        }

    def _total_unitary_actions(self):
        # constant for the env; quote the measured arc figure rather than
        # re-enumerating 72k actions (costs ~10s and never changes)
        return 72107
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_tools.py -v`
Expected: PASS (search takes ~3-5 s per test).

- [ ] **Step 5: Commit**

```bash
git add agent/tools.py tests/test_tools.py
git commit -m "feat: scoped topology search with action registry and exclusions"
```

---

### Task 4: `GridTools.simulate_action` and `apply_action`

**Files:**
- Modify: `agent/tools.py`
- Modify: `tests/test_tools.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tools.py`:

```python
def test_simulate_action_matches_search(tools, arc):
    res = tools.search_topology_actions(arc["scoped_subs"])
    best_id = res["candidates"][0]["action_id"]
    sim = tools.simulate_action(best_id)
    assert sim["action_id"] == best_id
    assert sim["diverged"] is False
    assert sim["simulated_max_rho"] == pytest.approx(
        res["candidates"][0]["simulated_max_rho"], abs=0.01)


def test_simulate_unknown_id_errors(tools):
    sim = tools.simulate_action("a-999-0")
    assert "error" in sim


def test_apply_action_rescues_grid(arc):
    from agent.tools import GridTools
    fresh = GridTools()                       # own instance: apply mutates env
    res = fresh.search_topology_actions(arc["scoped_subs"])
    best_id = res["candidates"][0]["action_id"]
    out = fresh.apply_action(best_id)
    assert out["applied"] is True
    assert out["max_rho"] == pytest.approx(
        arc["rescued_max_rho_applied"], abs=0.05)
    assert out["n_overloaded"] == 0
    assert out["stable"] is True
    assert out["stable_steps_checked"] >= arc["stable_steps_after_rescue"]
    # the real state moved: get_grid_state must reflect the rescue
    assert fresh.get_grid_state()["max_rho"] < 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_tools.py -v`
Expected: 3 new FAILs — missing `simulate_action` / `apply_action`.

- [ ] **Step 3: Implement**

Append to the `GridTools` class in `agent/tools.py`:

```python
    def simulate_action(self, action_id):
        act = self.registry.get(action_id)
        if act is None:
            return {"error": f"unknown action_id {action_id!r}; "
                             "run search_topology_actions first"}
        sim_obs, _, sim_done, _ = self.obs.simulate(act)
        if sim_done:
            return {"action_id": action_id, "diverged": True}
        reconnects, _ = self._action_effects(act, sim_obs)
        over = np.where(sim_obs.rho > 1.0)[0]
        return {
            "action_id": action_id,
            "diverged": False,
            "simulated_max_rho": round(float(sim_obs.rho.max()), 3),
            "simulated_n_overloaded": int(len(over)),
            "overloaded_lines": [int(l) for l in over],
            "reconnects_lines": reconnects,
        }

    def apply_action(self, action_id):
        act = self.registry.get(action_id)
        if act is None:
            return {"error": f"unknown action_id {action_id!r}; "
                             "run search_topology_actions first"}
        self.obs, _, self.done, _ = self.env.step(act)
        if self.done:
            return {"applied": True, "game_over": True,
                    "note": "grid collapsed after applying this action"}
        stable, worst_seen, steps = self._stability_check()
        return {
            "applied": True,
            "max_rho": round(float(self.obs.rho.max()), 3),
            "n_overloaded": int((self.obs.rho > 1.0).sum()),
            "stable_steps_checked": steps,
            "stable": stable,
            "worst_rho_during_check": round(worst_seen, 3),
        }

    def _stability_check(self):
        """Replay do-nothing on a copy of the env; the real env stays at the
        post-apply step. Stable = no game-over within the horizon."""
        sim_env = self.env.copy()
        do_nothing = sim_env.action_space({})
        worst = float(self.obs.rho.max())
        for step in range(config.STABILITY_CHECK_STEPS):
            obs, _, done, _ = sim_env.step(do_nothing)
            if done:
                return False, worst, step + 1
            worst = max(worst, float(obs.rho.max()))
        return True, worst, config.STABILITY_CHECK_STEPS
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_tools.py -v`
Expected: all PASS. If `env.copy()` raises (some Grid2Op versions restrict it), fall back inside `_stability_check` to `self.obs.simulate(do_nothing, time_step=k)` for k in 1..N and note the weaker guarantee in the returned dict as `"check_method": "forecast"`.

- [ ] **Step 5: Commit**

```bash
git add agent/tools.py tests/test_tools.py
git commit -m "feat: simulate_action and apply_action with stability check"
```

---

### Task 5: Tool schemas + dispatch

**Files:**
- Modify: `agent/tools.py`
- Modify: `tests/test_tools.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tools.py`:

```python
import json

from agent.tools import TOOLS_SCHEMA


def test_schema_names_match_methods(tools):
    names = [t["function"]["name"] for t in TOOLS_SCHEMA]
    assert names == ["get_grid_state", "search_topology_actions",
                     "simulate_action", "apply_action"]
    for name in names:
        assert callable(getattr(tools, name))


def test_dispatch_returns_compact_json(tools):
    out = tools.dispatch("get_grid_state", {})
    parsed = json.loads(out)
    assert "max_rho" in parsed
    assert len(out) <= 1500


def test_dispatch_unknown_tool(tools):
    out = json.loads(tools.dispatch("explode_grid", {}))
    assert "error" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_tools.py -v`
Expected: FAIL — `ImportError: cannot import name 'TOOLS_SCHEMA'`

- [ ] **Step 3: Implement schemas and dispatch**

Append to `agent/tools.py` (module level for `TOOLS_SCHEMA`, method on class for `dispatch`):

```python
    def dispatch(self, name, arguments):
        """Execute one tool call; always returns a JSON string capped in size."""
        import json
        if name not in ("get_grid_state", "search_topology_actions",
                        "simulate_action", "apply_action"):
            return json.dumps({"error": f"unknown tool {name!r}"})
        try:
            result = getattr(self, name)(**arguments)
        except TypeError as e:
            result = {"error": f"bad arguments for {name}: {e}"}
        out = json.dumps(result)
        if len(out) > config.MAX_TOOL_RESULT_CHARS:
            out = out[:config.MAX_TOOL_RESULT_CHARS] + '... (truncated)"}'
        return out


TOOLS_SCHEMA = [
    {"type": "function", "function": {
        "name": "get_grid_state",
        "description": ("Current grid state: worst loadings, overloaded "
                        "lines, disconnected lines, and a suggested search "
                        "scope. All values from the power-flow solver."),
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "search_topology_actions",
        "description": ("Simulate every unitary bus-split at the given "
                        "substations; returns candidates ranked by resulting "
                        "max line loading. Keep scope small (<=8 substations) "
                        "- the full grid has 72,107 actions and cannot be "
                        "searched in operator time."),
        "parameters": {"type": "object", "properties": {
            "substations": {"type": "array", "items": {"type": "integer"},
                            "description": "Substation ids to search, e.g. "
                            "candidate_scope_subs from get_grid_state."},
            "exclude_substations": {"type": "array",
                                    "items": {"type": "integer"},
                                    "description": "Substations unavailable "
                                    "for switching (crew on site etc)."},
        }, "required": ["substations"]},
    }},
    {"type": "function", "function": {
        "name": "simulate_action",
        "description": ("Simulate one candidate from a previous search "
                        "against the current state. Solver results only."),
        "parameters": {"type": "object", "properties": {
            "action_id": {"type": "string"},
        }, "required": ["action_id"]},
    }},
    {"type": "function", "function": {
        "name": "apply_action",
        "description": ("Apply an action to the REAL grid (not a "
                        "simulation), then verify stability over the next "
                        "steps. Use only after simulating."),
        "parameters": {"type": "object", "properties": {
            "action_id": {"type": "string"},
        }, "required": ["action_id"]},
    }},
]
```

- [ ] **Step 4: Run all tool tests**

Run: `.venv/bin/python -m pytest tests/test_tools.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/tools.py tests/test_tools.py
git commit -m "feat: OpenAI tool schemas and dispatch with output cap"
```

---

### Task 6: LLM tool-call loop

**Files:**
- Create: `agent/llm.py`
- Create: `tests/test_llm.py`

- [ ] **Step 1: Write the failing test (fake client, no server needed)**

`tests/test_llm.py`:

```python
import json
from types import SimpleNamespace as NS

from agent.llm import run_loop


def fake_response(content=None, tool_calls=None):
    return NS(choices=[NS(message=NS(
        role="assistant", content=content, tool_calls=tool_calls))])


def fake_tool_call(call_id, name, args):
    return NS(id=call_id, type="function",
              function=NS(name=name, arguments=json.dumps(args)))


def make_fake_client(script):
    state = {"i": 0, "seen_messages": []}

    def create(**kwargs):
        state["seen_messages"] = list(kwargs["messages"])
        resp = script[state["i"]]
        state["i"] += 1
        return resp

    client = NS(chat=NS(completions=NS(create=create)))
    return client, state


def test_loop_executes_tools_then_returns_narration():
    script = [
        fake_response(tool_calls=[
            fake_tool_call("c1", "get_grid_state", {})]),
        fake_response(content="Line 177 is overloaded; I will search."),
    ]
    client, state = make_fake_client(script)
    calls = []

    def dispatch(name, args):
        calls.append((name, args))
        return json.dumps({"max_rho": 1.30})

    events = []
    final = run_loop(client, "test-model",
                     [{"role": "user", "content": "grid status?"}],
                     tools_schema=[], dispatch=dispatch,
                     on_event=lambda kind, payload: events.append(kind))

    assert final == "Line 177 is overloaded; I will search."
    assert calls == [("get_grid_state", {})]
    # tool result fed back to the model on the second call
    roles = [m["role"] if isinstance(m, dict) else "assistant"
             for m in state["seen_messages"]]
    assert "tool" in roles
    assert events == ["tool", "narration"]


def test_loop_stops_at_max_iterations():
    looping = fake_response(tool_calls=[
        fake_tool_call("c1", "get_grid_state", {})])
    client, _ = make_fake_client([looping] * 20)
    final = run_loop(client, "test-model", [{"role": "user", "content": "x"}],
                     tools_schema=[], dispatch=lambda n, a: "{}",
                     max_iterations=3)
    assert "iteration limit" in final
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.llm'`

- [ ] **Step 3: Implement the loop**

`agent/llm.py`:

```python
"""Plain OpenAI chat-completions tool loop. No framework.

on_event(kind, payload) fires for UI artifacts:
  kind="tool"      payload={"tool", "arguments", "result"}
  kind="narration" payload={"text"}
"""
import json

from agent import config


def make_client():
    from openai import OpenAI
    return OpenAI(base_url=config.LLM_BASE_URL, api_key="local")


def _assistant_to_dict(message):
    d = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        d["tool_calls"] = [{
            "id": tc.id, "type": "function",
            "function": {"name": tc.function.name,
                         "arguments": tc.function.arguments},
        } for tc in message.tool_calls]
    return d


def run_loop(client, model, messages, tools_schema, dispatch,
             max_iterations=config.MAX_LOOP_ITERATIONS, on_event=None):
    """Run tool calls until the model produces plain text; returns that text.
    Mutates `messages` in place so conversation memory persists across turns."""
    emit = on_event or (lambda kind, payload: None)
    for _ in range(max_iterations):
        resp = client.chat.completions.create(
            model=model, messages=messages, tools=tools_schema)
        message = resp.choices[0].message
        messages.append(_assistant_to_dict(message))
        if not message.tool_calls:
            text = message.content or ""
            emit("narration", {"text": text})
            return text
        for tc in message.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = dispatch(tc.function.name, args)
            emit("tool", {"tool": tc.function.name, "arguments": args,
                          "result": result})
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": result})
    text = ("Stopped: iteration limit reached without a final answer. "
            "Grid state may still need attention.")
    emit("narration", {"text": text})
    return text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_llm.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/llm.py tests/test_llm.py
git commit -m "feat: OpenAI tool-call loop with event hook and iteration cap"
```

---

### Task 7: System prompt, cost table, scenario brief

**Files:**
- Create: `agent/prompts.py`

No unit test — prose module; correctness is judged in the end-to-end run (Task 12). Keep it importable and short.

- [ ] **Step 1: Write the module**

`agent/prompts.py`:

```python
"""System prompt, cost table, regulation excerpt.

Regulation excerpt and cost figures are DRAFTS for the energy-expert
teammate to review/replace (PRD section 12 team split).
"""

COST_TABLE = {
    "switching": "~free - no energy cost, only breaker wear",
    "redispatch": "expensive - generators paid to deviate, "
                  "order of 60-100 EUR per MWh shifted",
    "curtailment": "most expensive - compensation owed to operators "
                   "(EnWG 13a) plus regulatory reporting burden",
    "transformer_taps": "cheap, but mainly a voltage lever - "
                        "limited effect on thermal overloads",
}

REGULATION_EXCERPT = """\
Operating rules (excerpt, simplified for this exercise):
- N-1 principle: the grid must withstand the loss of any single element
  (line, transformer, generator) without cascading failures.
- Thermal limits: line loading (rho) above 100% trips protection relays
  after a short delay; sustained overloads cascade.
- After a contingency, the operator must return the system to a secure
  state within 15 minutes (N-0 restoration window).
- Remedial action preference order, cost- and regulation-aware:
  1) network switching (topology), 2) transformer taps,
  3) redispatch, 4) curtailment of load or renewables (last resort).
"""

SYSTEM_PROMPT = f"""\
You are a control-room assistant for a transmission grid operator. A
power-flow solver and a grid environment are available through tools.

Hard rules:
- Every number you state MUST come from a tool result in this
  conversation. Never estimate, never invent values.
- You never construct grid actions yourself. You search for candidates
  with search_topology_actions and refer to them only by action_id.
- Before applying an action, simulate it. After applying, re-check the
  grid state. If max_rho is still >= 1.0, search again with a wider
  scope (one more hop of substations). At most 2 apply attempts; if the
  grid is still insecure, say so honestly.
- If asked about an action type you have NOT simulated in this run
  (e.g. redispatch, curtailment), say so explicitly: "I have not
  simulated redispatch on this grid." Never quote results from other
  grids, past studies, or your training data as if they were
  measurements. You may compare costs qualitatively (see cost guidance)
  and cite your own measured switching results.
- If the operator reports a constraint in plain language (e.g. "crew on
  site at substation 67"), translate it into exclude_substations on
  your next search and say you did so.

Narration style:
- Speak like an operator: name the violated limit, the affected line
  (ids and substations), and the rule that requires acting.
- Justify the chosen action against the full menu - switching,
  transformer taps, redispatch, curtailment - using the cost guidance
  below. State why the cheaper-or-better options you rejected lose.
- Be concise: a few sentences per step, no filler.

Cost guidance:
{chr(10).join(f"- {k}: {v}" for k, v in COST_TABLE.items())}

{REGULATION_EXCERPT}
"""

SCENARIO_BRIEF = """\
Situation: you are connected to a live 118-bus transmission grid (Grid2Op
environment). The shift has just started and the grid may not be secure.
Operating context: early-evening load, demand still rising (ENTSO-E
German load curve). Begin by inspecting the grid state.
"""
```

- [ ] **Step 2: Smoke-check it imports and stays compact**

Run: `.venv/bin/python -c "from agent.prompts import SYSTEM_PROMPT; print(len(SYSTEM_PROMPT))"`
Expected: prints a number well under 4000 (local-model context budget).

- [ ] **Step 3: Commit**

```bash
git add agent/prompts.py
git commit -m "feat: system prompt with grounding rules, cost table, regulation excerpt"
```

---

### Task 8: Step artifacts writer

**Files:**
- Create: `agent/artifacts.py`
- Create: `tests/test_artifacts.py`

- [ ] **Step 1: Write the failing test**

`tests/test_artifacts.py`:

```python
import json
import os

from agent.artifacts import StepWriter


def test_steps_append_and_persist(tmp_path):
    w = StepWriter(str(tmp_path))
    w.add(kind="operator", text="grid status?")
    w.add(kind="tool", tool="get_grid_state",
          summary="max rho 1.30, 1 overloaded", max_rho=1.30,
          grid_status="overloaded")
    w.add(kind="narration", text="Line 177 overloaded...",
          render_zoom="renders/step_2_zoom.html")

    path = os.path.join(str(tmp_path), "steps.json")
    with open(path) as f:
        steps = json.load(f)
    assert [s["step"] for s in steps] == [1, 2, 3]
    assert steps[0]["kind"] == "operator"
    assert steps[1]["tool"] == "get_grid_state"
    assert steps[2]["render_zoom"].endswith("zoom.html")


def test_writer_starts_fresh_each_run(tmp_path):
    StepWriter(str(tmp_path)).add(kind="operator", text="old run")
    w2 = StepWriter(str(tmp_path))
    path = os.path.join(str(tmp_path), "steps.json")
    with open(path) as f:
        assert json.load(f) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_artifacts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.artifacts'`

- [ ] **Step 3: Implement**

`agent/artifacts.py`:

```python
"""Append-only step log for the UI. Rewrite-whole-file via temp+rename:
dumb and reliable beats websockets at hour 20 (SPEC section 6)."""
import json
import os


class StepWriter:
    def __init__(self, run_dir):
        os.makedirs(run_dir, exist_ok=True)
        self.path = os.path.join(run_dir, "steps.json")
        self.steps = []
        self._flush()

    def add(self, **step):
        step["step"] = len(self.steps) + 1
        self.steps.append(step)
        self._flush()

    def _flush(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.steps, f, indent=2)
        os.replace(tmp, self.path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_artifacts.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/artifacts.py tests/test_artifacts.py
git commit -m "feat: step artifact writer (UI data contract)"
```

---

### Task 9: Plotly renders (full + zoom) — legibility checkpoint

**Files:**
- Create: `agent/render.py`

No pytest — output is visual. The verification step IS the PRD §13 legibility checkpoint; do it now, not later.

- [ ] **Step 1: Implement the renderer**

`agent/render.py`:

```python
"""Per-state plotly renders: full grid overview + zoom to the affected area.
Render only on state change (open, post-apply), not per tool call."""
import os

from grid2op.PlotGrid import PlotPlotly


class GridRenderer:
    def __init__(self, observation_space, out_dir):
        self.plot = PlotPlotly(observation_space)
        self.layout = self.plot._grid_layout
        self.name_sub = observation_space.name_sub
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)

    def render(self, obs, tag, focus_subs=None):
        """Write {tag}_full.html and {tag}_zoom.html; return relative paths."""
        full = self._write(self.plot.plot_obs(obs), f"{tag}_full.html")
        zoom_fig = self.plot.plot_obs(obs)
        if focus_subs:
            pts = [self.layout[self.name_sub[s]] for s in focus_subs
                   if self.name_sub[s] in self.layout]
            if pts:
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                pad_x = max(20.0, 0.4 * (max(xs) - min(xs)))
                pad_y = max(20.0, 0.4 * (max(ys) - min(ys)))
                zoom_fig.update_layout(
                    xaxis_range=[min(xs) - pad_x, max(xs) + pad_x],
                    yaxis_range=[min(ys) - pad_y, max(ys) + pad_y])
        zoom = self._write(zoom_fig, f"{tag}_zoom.html")
        return full, zoom

    def _write(self, fig, filename):
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
        path = os.path.join(self.out_dir, filename)
        fig.write_html(path, include_plotlyjs="cdn", full_html=True)
        return path
```

- [ ] **Step 2: Generate checkpoint renders from the demo scenario**

Run:

```bash
MPLCONFIGDIR=$TMPDIR/mpl .venv/bin/python -c "
from agent.tools import GridTools
from agent.render import GridRenderer
from agent import config
t = GridTools()
r = GridRenderer(t.env.observation_space, config.RENDER_DIR)
state = t.get_grid_state()
print(r.render(t.obs, 'check_crisis', focus_subs=state['candidate_scope_subs']))
"
```

Expected: prints two paths under `artifacts/run/renders/`.

- [ ] **Step 3: MANUAL CHECKPOINT — verify projector legibility (PRD §13)**

Open `artifacts/run/renders/check_crisis_zoom.html` in a browser. Check: the
overloaded line (177, subs 115→67) is visibly red and distinguishable at
projector distance; substation labels readable. If the zoom view is unusable,
this is a STOP-and-rethink moment (fall back: plotly's built-in zoom/pan live
on stage, full view only). Record the verdict in the commit message.

- [ ] **Step 4: Commit**

```bash
git add agent/render.py
git commit -m "feat: full+zoom plotly renders; legibility checkpoint: <PASS/FALLBACK>"
```

---

### Task 10: Main entrypoint — wiring, operator input, inbox polling

**Files:**
- Create: `agent/main.py`

- [ ] **Step 1: Implement**

`agent/main.py`:

```python
"""Demo entrypoint.

  .venv/bin/python -m agent.main                 # stdin operator input
  .venv/bin/python -m agent.main --inbox         # poll UI inbox file

Each operator message runs one tool-loop turn; conversation memory
persists across turns (follow-up questions answered from prior results).
"""
import argparse
import json
import os
import time

from agent import config
from agent.artifacts import StepWriter
from agent.llm import make_client, run_loop
from agent.prompts import SCENARIO_BRIEF, SYSTEM_PROMPT
from agent.render import GridRenderer
from agent.tools import TOOLS_SCHEMA, GridTools


class Inbox:
    """Operator messages from the UI: artifacts/run/inbox.json, a JSON list
    of {"text": ...}. File-based both ways - no sockets (SPEC section 6)."""

    def __init__(self, run_dir):
        self.path = os.path.join(run_dir, "inbox.json")
        self.consumed = 0
        if not os.path.exists(self.path):
            with open(self.path, "w") as f:
                json.dump([], f)

    def next_message(self):
        while True:
            try:
                with open(self.path) as f:
                    items = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                items = []
            if len(items) > self.consumed:
                msg = items[self.consumed]["text"]
                self.consumed += 1
                return msg
            time.sleep(0.5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbox", action="store_true",
                        help="read operator messages from UI inbox file")
    args = parser.parse_args()

    tools = GridTools()
    client = make_client()
    writer = StepWriter(config.RUN_DIR)
    renderer = GridRenderer(tools.env.observation_space, config.RENDER_DIR)
    inbox = Inbox(config.RUN_DIR) if args.inbox else None

    def grid_status():
        return "rescued" if tools.obs.rho.max() < 1.0 else "overloaded"

    def emit_render(tag):
        scope = tools.get_grid_state()["candidate_scope_subs"] or None
        full, zoom = renderer.render(tools.obs, tag, focus_subs=scope)
        rel = lambda p: os.path.relpath(p, config.ROOT)
        return rel(full), rel(zoom)

    full, zoom = emit_render("step_0_open")
    writer.add(kind="narration", text="Connected to grid.",
               grid_status=grid_status(),
               max_rho=round(float(tools.obs.rho.max()), 3),
               render_full=full, render_zoom=zoom)

    def on_event(kind, payload):
        entry = {"kind": kind, "grid_status": grid_status(),
                 "max_rho": round(float(tools.obs.rho.max()), 3)}
        if kind == "tool":
            entry["tool"] = payload["tool"]
            entry["summary"] = payload["result"][:200]
            if payload["tool"] == "apply_action":
                tag = f"step_{len(writer.steps)}_applied"
                entry["render_full"], entry["render_zoom"] = emit_render(tag)
        else:
            entry["text"] = payload["text"]
        writer.add(**entry)

    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": SCENARIO_BRIEF}]

    print("Operator console. Type message (or 'quit').")
    while True:
        if inbox:
            operator_msg = inbox.next_message()
        else:
            operator_msg = input("operator> ").strip()
        if operator_msg.lower() in ("quit", "exit"):
            break
        if not operator_msg:
            continue
        if len(messages) > 2 or messages[-1]["role"] != "user":
            messages.append({"role": "user", "content": operator_msg})
        else:
            messages[-1]["content"] += "\n\nOperator: " + operator_msg
        writer.add(kind="operator", text=operator_msg)
        final = run_loop(client, config.LLM_MODEL, messages,
                         TOOLS_SCHEMA, tools.dispatch, on_event=on_event)
        print(f"\nagent> {final}\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test the wiring without the LLM**

Imports and step-0 artifact must work even with no server running:

Run:

```bash
MPLCONFIGDIR=$TMPDIR/mpl .venv/bin/python -c "
import agent.main  # import-time errors surface here
print('imports ok')
"
```

Expected: `imports ok`.

- [ ] **Step 3: Run existing test suite (regression)**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add agent/main.py
git commit -m "feat: demo entrypoint with operator console and UI inbox"
```

---

### Task 11: Demo UI — server + page

**Files:**
- Create: `ui/serve.py`
- Create: `ui/index.html`

- [ ] **Step 1: Implement the server (stdlib only)**

`ui/serve.py`:

```python
"""Static file server + one POST endpoint for the operator inbox.

Run from grid-agent/:  .venv/bin/python ui/serve.py
Page: http://localhost:8000/ui/index.html
"""
import json
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INBOX = os.path.join(ROOT, "artifacts", "run", "inbox.json")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_POST(self):
        if self.path != "/inbox":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        os.makedirs(os.path.dirname(INBOX), exist_ok=True)
        try:
            with open(INBOX) as f:
                items = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            items = []
        items.append({"text": body["text"]})
        with open(INBOX, "w") as f:
            json.dump(items, f)
        self.send_response(204)
        self.end_headers()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    print("serving on http://localhost:8000/ui/index.html")
    HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
```

- [ ] **Step 2: Implement the page**

`ui/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Voltify — Grid Operation Agent</title>
<style>
  :root { --red: #c0392b; --green: #27ae60; --bg: #11151c; --panel: #1a2029;
          --text: #e8eaed; --muted: #8a93a2; }
  * { box-sizing: border-box; }
  body { margin: 0; display: flex; height: 100vh; font: 15px/1.45 system-ui,
         sans-serif; background: var(--bg); color: var(--text); }
  #left { flex: 1.4; display: flex; flex-direction: column; padding: 12px; }
  #right { flex: 1; display: flex; flex-direction: column;
           border-left: 1px solid #2a3240; }
  header { display: flex; align-items: baseline; gap: 12px; padding: 4px 8px; }
  h1 { font-size: 18px; margin: 0; }
  #status { font-weight: 700; padding: 2px 10px; border-radius: 12px; }
  #status.overloaded { background: var(--red); }
  #status.rescued { background: var(--green); }
  #viewtoggle { margin-left: auto; color: var(--muted); cursor: pointer; }
  iframe { flex: 1; border: 0; background: #fff; border-radius: 6px; }
  #feed { flex: 1; overflow-y: auto; padding: 12px; }
  .msg { margin: 8px 0; padding: 8px 12px; border-radius: 8px;
         max-width: 92%; white-space: pre-wrap; }
  .operator { background: #2b3a55; margin-left: auto; }
  .narration { background: var(--panel); }
  .tool { color: var(--muted); font-size: 12px; font-family: monospace;
          padding: 2px 12px; }
  form { display: flex; gap: 8px; padding: 12px; border-top: 1px solid #2a3240; }
  input { flex: 1; padding: 10px; border-radius: 6px; border: 1px solid
          #2a3240; background: var(--panel); color: var(--text); }
  button { padding: 10px 18px; border: 0; border-radius: 6px;
           background: #3b6ad6; color: #fff; cursor: pointer; }
</style>
</head>
<body>
<div id="left">
  <header>
    <h1>Voltify — Grid Operation Agent</h1>
    <span id="status" class="overloaded">…</span>
    <span id="maxrho"></span>
    <span id="viewtoggle">⤢ full grid</span>
  </header>
  <iframe id="grid" src="about:blank"></iframe>
</div>
<div id="right">
  <div id="feed"></div>
  <form id="opform">
    <input id="opmsg" placeholder="Operator message…" autocomplete="off">
    <button>Send</button>
  </form>
</div>
<script>
let nSteps = 0, zoomed = true, renders = {full: null, zoom: null};

function setRender() {
  const src = zoomed ? renders.zoom : renders.full;
  const frame = document.getElementById('grid');
  if (src && frame.getAttribute('data-src') !== src) {
    frame.src = '/' + src; frame.setAttribute('data-src', src);
  }
}

document.getElementById('viewtoggle').onclick = () => {
  zoomed = !zoomed;
  document.getElementById('viewtoggle').textContent =
    zoomed ? '⤢ full grid' : '⤡ zoom to fault';
  setRender();
};

async function poll() {
  try {
    const r = await fetch('/artifacts/run/steps.json?t=' + Date.now());
    const steps = await r.json();
    const feed = document.getElementById('feed');
    for (const s of steps.slice(nSteps)) {
      const div = document.createElement('div');
      if (s.kind === 'tool') {
        div.className = 'tool';
        div.textContent = '⚙ ' + s.tool;
      } else {
        div.className = 'msg ' + s.kind;
        div.textContent = s.text || '';
      }
      feed.appendChild(div);
      if (s.render_full) renders.full = s.render_full;
      if (s.render_zoom) renders.zoom = s.render_zoom;
      if (s.grid_status) {
        const el = document.getElementById('status');
        el.textContent = s.grid_status;
        el.className = s.grid_status;
        document.getElementById('maxrho').textContent =
          'max ρ ' + (s.max_rho ?? '');
      }
    }
    if (steps.length > nSteps) {
      nSteps = steps.length;
      feed.scrollTop = feed.scrollHeight;
      setRender();
    }
  } catch (e) { /* agent not started yet — keep polling */ }
}
setInterval(poll, 1000);

document.getElementById('opform').onsubmit = async (e) => {
  e.preventDefault();
  const box = document.getElementById('opmsg');
  if (!box.value.trim()) return;
  await fetch('/inbox', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({text: box.value.trim()})});
  box.value = '';
};
</script>
</body>
</html>
```

- [ ] **Step 3: MANUAL CHECKPOINT — test UI with synthetic steps**

Run (writes a fake steps file, starts server):

```bash
MPLCONFIGDIR=$TMPDIR/mpl .venv/bin/python -c "
from agent.artifacts import StepWriter
from agent import config
w = StepWriter(config.RUN_DIR)
w.add(kind='operator', text='Grid status please.')
w.add(kind='tool', tool='get_grid_state', summary='max rho 1.30',
      grid_status='overloaded', max_rho=1.30,
      render_zoom='artifacts/run/renders/check_crisis_zoom.html',
      render_full='artifacts/run/renders/check_crisis_full.html')
w.add(kind='narration', text='Line 177 (115-67) at 130%. Searching.',
      grid_status='overloaded', max_rho=1.30)
"
.venv/bin/python ui/serve.py
```

Open `http://localhost:8000/ui/index.html`. Verify: feed shows 3 entries,
status chip red "overloaded", grid iframe shows the crisis render, zoom
toggle works, sending a message appends to `artifacts/run/inbox.json`
(check file content). Ctrl-C the server when done.

- [ ] **Step 4: Commit**

```bash
git add ui/serve.py ui/index.html
git commit -m "feat: demo UI - polling page plus stdlib server with inbox POST"
```

---

### Task 12: KEYSTONE — end-to-end run against the local LLM

**Files:** none new — this is the integration verification for Tasks 1–11.

Requires the local model server running at `localhost:8003/v1` (presenter machine). Everything before this task works without it.

- [ ] **Step 1: Start the stack**

Terminal A: confirm model server is up: `curl -s http://localhost:8003/v1/models | head -c 300`
Terminal B: `.venv/bin/python ui/serve.py`
Terminal C: `MPLCONFIGDIR=$TMPDIR/mpl .venv/bin/python -m agent.main --inbox`

- [ ] **Step 2: Run the demo arc from the UI**

In the browser, send: `Shift start. Please check the grid and secure it if needed.`

Expected agent behavior (watch the feed):
1. calls `get_grid_state` → reports line 177 at ~1.30
2. calls `search_topology_actions` with the scope subs → finds sub-67 split
3. (optionally) `simulate_action` on the best id
4. calls `apply_action` → rho ~0.81, stable; render flips red → green
5. narrates each step in operator language

- [ ] **Step 3: Verify the grounding invariant**

Read the narration in the feed. Every number (1.30, 177, 0.80, counts,
seconds) must appear in some tool result. Spot-check against the `⚙` tool
entries. Any invented number = fix the system prompt (strengthen the hard
rule, or shrink tool output further) and re-run.

- [ ] **Step 4: Test the follow-up beat**

Send: `Why not redispatch instead?`
Expected: agent states explicitly that redispatch was NOT simulated in
this run, then argues from the cost table and its own measured switching
results (rho 0.80 at ~zero cost). Any number not present in a tool result
— especially any rho figure for redispatch — is a FAIL: fix the system
prompt's not-simulated rule and re-run. (Redispatch probes are
deliberately NOT a tool — SPEC §3.4 upgrade path: add 2-3 grounded probes
to the search tool only if this honest answer sounds weak in rehearsal
AND time remains at hour ~6.)

- [ ] **Step 5: Record the result**

If the arc completes: commit any prompt tweaks made during the run:

```bash
git add -A
git commit -m "feat: end-to-end demo arc verified against local LLM"
```

If the model fails the arc repeatedly (wrong tool order, ignores scope):
tighten `SYSTEM_PROMPT` flow nudge first; second lever is reducing
`TOP_K_CANDIDATES` to 3. Do NOT add new tools or framework.

---

### Task 13: Constraint twist — verify second-best rescue (PRD §13 open item)

**Files:**
- Create: `verify_second_best.py` (top level, matching `verify_118_arc.py` convention)

- [ ] **Step 1: Write the verification script**

`verify_second_best.py`:

```python
"""PRD section 13 open item: with substation 67 excluded ("crew on site"),
does another scoped substation still rescue the grid? Tools-layer only,
no LLM. Saves the proven record for the demo crib sheet."""
import json
import os

from agent import config
from agent.tools import GridTools

ARC = json.load(open(os.path.join(config.ROOT, "scenarios", "arc_118.json")))


def main():
    tools = GridTools()
    res = tools.search_topology_actions(
        ARC["scoped_subs"],
        exclude_substations=[ARC["rescue_substation"]])
    if not res["candidates"]:
        print("NO-GO: no candidates with sub 67 excluded. "
              "Try widening: tools._scoped_subs(n_hops=2)")
        return
    best = res["candidates"][0]
    print("best without sub 67:", json.dumps(best, indent=2))
    if best["simulated_max_rho"] >= 1.0:
        print("NO-GO: second-best does not rescue (rho >= 1.0). "
              "Constraint-twist beat needs a different exclusion - "
              "try excluding a non-critical scoped sub instead.")
        return
    out = tools.apply_action(best["action_id"])
    print("applied:", json.dumps(out, indent=2))
    record = {"excluded_substation": ARC["rescue_substation"],
              "second_best": best, "applied": out,
              "verified_from": "verify_second_best.py"}
    path = os.path.join(config.ROOT, "scenarios", "second_best_118.json")
    with open(path, "w") as f:
        json.dump(record, f, indent=2)
    print("GO - saved", path)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

Run: `MPLCONFIGDIR=$TMPDIR/mpl .venv/bin/python verify_second_best.py`
Expected: `GO - saved .../scenarios/second_best_118.json` with rho < 1.0.
If NO-GO: the constraint-twist demo beat changes — follow the script's
hint (wider scope, or exclude a different substation) and update the crib
sheet accordingly. This is exactly why we verify before stage.

- [ ] **Step 3: Re-verify the twist through the LLM (stack from Task 12 up)**

Restart `agent.main`, run the demo arc, then send:
`Hold on - substation 67 is unavailable, maintenance crew on site.`
Expected: agent re-searches with `exclude_substations=[67]`, picks the
verified second-best, explains the constraint.

- [ ] **Step 4: Commit**

```bash
git add verify_second_best.py scenarios/second_best_118.json
git commit -m "feat: verify constraint-twist second-best rescue (PRD open item)"
```

---

### Task 14: Screening table (deliverable 2)

**Files:**
- Create: `bench/__init__.py` (empty)
- Create: `bench/screening.py`

- [ ] **Step 1: Implement**

`bench/screening.py`:

```python
"""Deliverable 2: classify all 186 single-line N-1 outages relative to the
STRESSED baseline (PRD section 9: naive rho>1 marks 184/186 dangerous;
danger = divergence, or materially worse than the already-stressed state).

Run: .venv/bin/python -m bench.screening
Output: artifacts/screening_118.json + artifacts/screening_118.md
"""
import json
import os
import time

import numpy as np

from agent import config
from agent.tools import GridTools

RHO_DELTA = 0.05   # worse than baseline by more than this = dangerous


def main():
    tools = GridTools()
    obs, env = tools.obs, tools.env
    base_max = float(obs.rho.max())
    base_over = int((obs.rho > 1.0).sum())
    rows, t0 = [], time.time()
    for line_id in range(env.n_line):
        if not obs.line_status[line_id]:
            continue
        act = env.action_space({"set_line_status": [(int(line_id), -1)]})
        sim_obs, _, sim_done, _ = obs.simulate(act)
        if sim_done:
            verdict, worst, n_over = "dangerous-diverged", None, None
        else:
            worst = float(sim_obs.rho.max())
            n_over = int((sim_obs.rho > 1.0).sum())
            worse = (worst - base_max) > RHO_DELTA or n_over > base_over
            verdict = "dangerous" if worse else "harmless-vs-baseline"
        rows.append({"line_id": int(line_id),
                     "from_sub": int(obs.line_or_to_subid[line_id]),
                     "to_sub": int(obs.line_ex_to_subid[line_id]),
                     "max_rho_after": worst, "n_overloaded_after": n_over,
                     "verdict": verdict})
    elapsed = round(time.time() - t0, 1)
    summary = {
        "baseline_max_rho": base_max, "baseline_n_overloaded": base_over,
        "n_screened": len(rows), "screening_seconds": elapsed,
        "n_dangerous": sum(r["verdict"].startswith("dangerous") for r in rows),
        "n_diverged": sum(r["verdict"] == "dangerous-diverged" for r in rows),
        "rho_delta_threshold": RHO_DELTA,
        "outages": rows,
    }
    out_json = os.path.join(config.ROOT, "artifacts", "screening_118.json")
    with open(out_json, "w") as f:
        json.dump(summary, f, indent=2)

    dangerous = [r for r in rows if r["verdict"].startswith("dangerous")]
    dangerous.sort(key=lambda r: -(r["max_rho_after"] or 99))
    lines = [f"# N-1 screening — 118-bus grid, stressed baseline "
             f"(max rho {base_max:.2f})",
             "",
             f"{len(rows)} outages screened in {elapsed}s — "
             f"{summary['n_dangerous']} dangerous "
             f"({summary['n_diverged']} diverged), "
             f"{len(rows) - summary['n_dangerous']} harmless vs baseline.",
             "",
             "| line | subs | max rho after | verdict |",
             "|---|---|---|---|"]
    for r in dangerous[:20]:
        rho_txt = "diverged" if r["max_rho_after"] is None \
            else f"{r['max_rho_after']:.2f}"
        lines.append(f"| {r['line_id']} | {r['from_sub']}->{r['to_sub']} "
                     f"| {rho_txt} | {r['verdict']} |")
    out_md = os.path.join(config.ROOT, "artifacts", "screening_118.md")
    with open(out_md, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"screened {len(rows)} in {elapsed}s -> "
          f"{summary['n_dangerous']} dangerous. Wrote {out_json}, {out_md}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

Run: `MPLCONFIGDIR=$TMPDIR/mpl .venv/bin/python -m bench.screening`
Expected: ~186 outages screened in ~6 s; dangerous count well under 184
(the naive-cutoff number) — sanity-check the threshold splits meaningfully.

- [ ] **Step 3: Commit**

```bash
git add bench/__init__.py bench/screening.py artifacts/screening_118.json artifacts/screening_118.md
git commit -m "feat: N-1 screening table relative to stressed baseline (deliverable 2)"
```

---

### Task 15: Benchmark table (deliverable 3)

**Files:**
- Create: `bench/benchmark.py`

- [ ] **Step 1: Implement**

`bench/benchmark.py`:

```python
"""Deliverable 3: agent vs scoped brute-force vs do-nothing, per-scenario
one-shot rescue (PRD section 9 wording). Scenarios = the demo crisis plus
the worst non-diverged dangerous outages from screening.

Brute-force and do-nothing run without the LLM:
    .venv/bin/python -m bench.benchmark
Agent column needs the model server:
    .venv/bin/python -m bench.benchmark --with-agent --limit 5

Blind brute-force over all 72,107 actions (~38 min at 32 ms/solve) is
QUOTED, never run.
"""
import argparse
import json
import os
import time

from agent import config
from agent.llm import make_client, run_loop
from agent.prompts import SCENARIO_BRIEF, SYSTEM_PROMPT
from agent.tools import TOOLS_SCHEMA, GridTools

BLIND_BRUTE_FORCE_NOTE = "72107 actions x ~32 ms = ~38 min (quoted, not run)"


def load_scenarios(limit):
    path = os.path.join(config.ROOT, "artifacts", "screening_118.json")
    with open(path) as f:
        screening = json.load(f)
    worst = [r for r in screening["outages"] if r["verdict"] == "dangerous"]
    worst.sort(key=lambda r: -(r["max_rho_after"] or 0))
    # None = the crisis-at-open demo scenario (no extra outage injected)
    return [None] + [r["line_id"] for r in worst[:limit - 1]]


def setup(outage_line):
    tools = GridTools()
    if outage_line is not None:
        act = tools.env.action_space(
            {"set_line_status": [(int(outage_line), -1)]})
        tools.obs, _, tools.done, _ = tools.env.step(act)
    return tools


def run_do_nothing(outage_line):
    tools = setup(outage_line)
    if tools.done:
        return {"rescued": False, "note": "game over at outage"}
    stable, worst, steps = tools._stability_check()
    return {"rescued": bool(stable and worst < 1.0),
            "survived_steps": steps, "worst_rho": worst}


def run_brute_force(outage_line):
    tools = setup(outage_line)
    if tools.done:
        return {"rescued": False, "note": "game over at outage"}
    t0 = time.time()
    scope = tools._scoped_subs(n_hops=1)
    res = tools.search_topology_actions(scope)
    if not res["candidates"]:
        return {"rescued": False, "wallclock_s": round(time.time() - t0, 1)}
    best = res["candidates"][0]
    applied = tools.apply_action(best["action_id"])
    return {"rescued": bool(applied.get("max_rho", 9) < 1.0),
            "actions_taken": 1,
            "actions_simulated": res["actions_simulated"],
            "wallclock_s": round(time.time() - t0, 1)}


def run_agent(outage_line):
    tools = setup(outage_line)
    if tools.done:
        return {"rescued": False, "note": "game over at outage"}
    client = make_client()
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": SCENARIO_BRIEF +
                 "\nOperator: check the grid and secure it if needed."}]
    applies = []
    t0 = time.time()

    def on_event(kind, payload):
        if kind == "tool" and payload["tool"] == "apply_action":
            applies.append(payload)

    run_loop(client, config.LLM_MODEL, messages, TOOLS_SCHEMA,
             tools.dispatch, on_event=on_event)
    return {"rescued": bool(float(tools.obs.rho.max()) < 1.0
                            and not tools.done),
            "actions_taken": len(applies),
            "wallclock_s": round(time.time() - t0, 1)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-agent", action="store_true")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    results = []
    for outage in load_scenarios(args.limit):
        name = "crisis-at-open" if outage is None else f"outage-line-{outage}"
        print(f"== {name}")
        row = {"scenario": name,
               "do_nothing": run_do_nothing(outage),
               "scoped_brute_force": run_brute_force(outage)}
        if args.with_agent:
            row["agent"] = run_agent(outage)
        results.append(row)

    out = {"blind_brute_force": BLIND_BRUTE_FORCE_NOTE, "results": results}
    out_json = os.path.join(config.ROOT, "artifacts", "benchmark_118.json")
    with open(out_json, "w") as f:
        json.dump(out, f, indent=2)

    cols = ["do_nothing", "scoped_brute_force"] + \
        (["agent"] if args.with_agent else [])
    lines = ["# Benchmark — one-shot rescue per scenario", "",
             f"Blind brute force: {BLIND_BRUTE_FORCE_NOTE}", "",
             "| scenario | " + " | ".join(cols) + " |",
             "|" + "---|" * (len(cols) + 1)]
    for r in results:
        cells = []
        for c in cols:
            d = r[c]
            mark = "rescued" if d.get("rescued") else "FAILED"
            extra = f" ({d['wallclock_s']}s)" if "wallclock_s" in d else ""
            cells.append(mark + extra)
        lines.append(f"| {r['scenario']} | " + " | ".join(cells) + " |")
    out_md = os.path.join(config.ROOT, "artifacts", "benchmark_118.md")
    with open(out_md, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("wrote", out_json, "and", out_md)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run without the agent column**

Run: `MPLCONFIGDIR=$TMPDIR/mpl .venv/bin/python -m bench.benchmark --limit 5`
Expected: 5 scenario rows; brute-force rescues most; do-nothing fails the
crisis scenario (blackout). Inspect `artifacts/benchmark_118.md`.

- [ ] **Step 3: Run with the agent column (model server up)**

Run: `MPLCONFIGDIR=$TMPDIR/mpl .venv/bin/python -m bench.benchmark --with-agent --limit 5`
Expected: agent column populated. Honesty rule (SPEC §7): brute-force may
beat the agent on success rate within its scope — the table says so; the
pitch argues the messiness thesis on top. Do not tune the benchmark to
flatter the agent.

- [ ] **Step 4: Commit**

```bash
git add bench/benchmark.py artifacts/benchmark_118.json artifacts/benchmark_118.md
git commit -m "feat: benchmark table - agent vs scoped brute-force vs do-nothing (deliverable 3)"
```

---

### Task 16: Presenter crib sheet

**Files:**
- Create: `scenarios/crib_sheet.md`

- [ ] **Step 1: Write it**

`scenarios/crib_sheet.md`:

```markdown
# Demo crib sheet — nothing improvised on stage

## Pre-flight (before judges arrive)
1. Model server up: `curl -s http://localhost:8003/v1/models`
2. `cd grid-agent && .venv/bin/python ui/serve.py` (terminal 1)
3. `MPLCONFIGDIR=$TMPDIR/mpl .venv/bin/python -m agent.main --inbox` (terminal 2)
4. Browser: http://localhost:8000/ui/index.html — status chip red, crisis render visible
5. Network OFF is fine — everything is localhost (say this out loud, it's a pitch point)

## Script (send from the UI input box, in order)

1. `Shift start. Please check the grid and secure it if needed.`
   → expect: inspect → scoped search (88 of 72,107 actions, ~3 s) →
     bus-split at substation 67 → max rho 0.80, render flips green.
   Talking point: do-nothing = blackout in 4 steps (measured); the agent
   scoped a 38-minute search space down to 3 seconds.

2. `Why not redispatch instead?`
   → expect: agent says redispatch was not simulated this run, then argues
     cost: switching reached rho 0.80 at ~zero cost, redispatch costs
     60-100 EUR/MWh. If a judge asks "is that number from this grid?" —
     every quoted rho is in the tool feed on screen. That honesty IS the
     pitch; don't apologize for it.

3. (Reset the run: restart agent.main) then after the search step, send:
   `Hold on - substation 67 is unavailable, maintenance crew on site.`
   → expect: re-search with exclude_substations=[67], second-best action
     per scenarios/second_best_118.json, explanation of the constraint.
   Talking point: same overload, new sentence, different action — this is
   what the optimizer can't do without a programmer.

## If the model goes off-script
- Wrong numbers in narration: point at the tool feed — every number it may
  use is on screen; restart the turn.
- Search of wrong/huge scope: the tool refuses >cap substations and says so;
  re-send the message.
- Total stall: restart agent.main (state reloads to crisis-at-open in ~10 s).

## Numbers to have in your head
- 118 buses, 186 lines; 72,107 topology actions; 32 ms per power flow
- blind search ~38 min vs scoped 88 actions in 3 s
- crisis: line 177 (115→67) at 130%; rescue: bus-split sub 67 → 80%
- do-nothing: blackout in 4 steps; rescued state stable 20+ steps
```

- [ ] **Step 2: Verify the numbers against artifacts**

Cross-check every number in the crib sheet against `scenarios/arc_118.json`
and `scenarios/second_best_118.json` (from Task 13). Fix mismatches in the
crib sheet, never in the data.

- [ ] **Step 3: Commit and push**

```bash
git add scenarios/crib_sheet.md
git commit -m "docs: presenter crib sheet"
git push
```

---

## Spec coverage map (self-review)

| SPEC section | Task |
|---|---|
| §1 architecture, local LLM, env, time model | 1, 6, 10 |
| §2 file layout | 1–11, 14–15 |
| §3 four tools + registry + compact output | 2–5 |
| §3.4 redispatch decision point | 12 step 4 |
| §4 loop, flow nudge, constraint twist, follow-ups | 6, 7, 10, 12, 13 |
| §5 scenario management | 10 (chronic 0), 15 (dangerous subset) |
| §6 UI data contract, inbox, renders on state change | 8, 9, 10, 11 |
| §7 screening + benchmark + honesty rule | 14, 15 |
| §8 config | 1 |
| §9 build order | task order mirrors it; cut line after Task 13 |
| §10 verification (golden test, grounding, twist, offline) | 2–5 (golden), 12 (grounding+offline), 13 (twist) |

Cut line if time runs out (mirrors SPEC §9): Tasks 1–12 are the demo;
Task 13 is the best beat (cheap, verify early — may be pulled before 12 if
the LLM machine is busy); Tasks 14–15 are slides; Task 16 is required for
stage but is mostly transcription.
