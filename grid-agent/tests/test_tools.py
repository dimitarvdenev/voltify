import json

import pytest

from agent.tools import TOOLS_SCHEMA


def test_get_grid_state_reports_crisis(tools, arc):
    state = tools.get_grid_state()
    assert state["max_rho"] == pytest.approx(arc["crisis_max_rho"], abs=0.05)
    assert state["n_overloaded"] >= 1
    overloaded_ids = [line["line_id"] for line in state["overloaded_lines"]]
    assert arc["crisis_line_id"] in overloaded_ids
    crisis = next(
        line
        for line in state["overloaded_lines"]
        if line["line_id"] == arc["crisis_line_id"]
    )
    assert {crisis["from_sub"], crisis["to_sub"]} == set(arc["crisis_line_subs"])
    assert len(state["top_loaded_lines"]) <= 5
    assert set(arc["scoped_subs"]) <= set(state["candidate_scope_subs"])


def test_search_finds_proven_rescue(tools, arc):
    res = tools.search_topology_actions(arc["scoped_subs"])
    assert res["actions_simulated"] > 50
    assert res["actions_total_grid"] > 70000
    assert 1 <= len(res["candidates"]) <= 5
    best = res["candidates"][0]
    assert best["substation"] == arc["rescue_substation"]
    assert best["simulated_max_rho"] == pytest.approx(
        arc["rescued_max_rho_simulated"], abs=0.05
    )
    assert best["simulated_max_rho"] < 1.0
    assert best["action_id"] in tools.registry
    assert best["cost_class"].startswith("switching")


def test_search_respects_exclusions(tools, arc):
    res = tools.search_topology_actions(
        arc["scoped_subs"], exclude_substations=[arc["rescue_substation"]]
    )
    assert all(
        candidate["substation"] != arc["rescue_substation"]
        for candidate in res["candidates"]
    )


def test_simulate_action_matches_search(tools, arc):
    res = tools.search_topology_actions(arc["scoped_subs"])
    best_id = res["candidates"][0]["action_id"]
    sim = tools.simulate_action(best_id)
    assert sim["action_id"] == best_id
    assert sim["diverged"] is False
    assert sim["simulated_max_rho"] == pytest.approx(
        res["candidates"][0]["simulated_max_rho"], abs=0.01
    )


def test_simulate_unknown_id_errors(tools):
    sim = tools.simulate_action("a-999-0")
    assert "error" in sim


def test_apply_action_rescues_grid(arc):
    from agent.tools import GridTools

    fresh = GridTools()
    res = fresh.search_topology_actions(arc["scoped_subs"])
    best_id = res["candidates"][0]["action_id"]
    out = fresh.apply_action(best_id)
    assert out["applied"] is True
    assert out["max_rho"] == pytest.approx(arc["rescued_max_rho_applied"], abs=0.05)
    assert out["n_overloaded"] == 0
    assert out["stable"] is True
    assert out["stable_steps_checked"] >= arc["stable_steps_after_rescue"]
    assert fresh.get_grid_state()["max_rho"] < 1.0


def test_schema_names_match_methods(tools):
    names = [tool["function"]["name"] for tool in TOOLS_SCHEMA]
    assert names == [
        "get_grid_state",
        "search_topology_actions",
        "simulate_action",
        "apply_action",
    ]
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
