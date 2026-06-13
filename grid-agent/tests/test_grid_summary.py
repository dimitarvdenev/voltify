import pytest

from agent.grid_summary import (
    apply_derates,
    derate_map,
    line_summary,
    scoped_substations,
    summarize_grid_state,
)


def test_line_summary_reports_endpoint_labels(tools, arc):
    summary = line_summary(tools.env, tools.obs, arc["crisis_line_id"])

    assert summary["line_id"] == arc["crisis_line_id"]
    assert {summary["from_sub"], summary["to_sub"]} == set(arc["crisis_line_subs"])
    assert summary["rho"] == pytest.approx(arc["crisis_max_rho"], abs=0.05)
    assert "Line" in summary["line_label"]


def test_scoped_substations_grows_from_overloaded_endpoints(tools, arc):
    scoped = scoped_substations(tools.env, tools.obs, n_hops=1)

    assert set(arc["crisis_line_subs"]) <= set(scoped)
    assert set(arc["scoped_subs"]) <= set(scoped)


def test_derate_map_and_application():
    board = {
        "constraints": [
            {"kind": "note", "line_id": 3, "pct": 99},
            {"kind": "derate", "line_id": 4, "pct": 10.0},
        ]
    }
    derates = derate_map(board)

    assert derates == {4: 10.0}
    assert apply_derates({"line_id": 4, "rho": 0.9}, derates) == {
        "line_id": 4,
        "rho": 0.9,
        "derate_pct": 10.0,
        "effective_rho": 1.0,
    }


def test_summarize_grid_state_includes_derated_effective_rho(tools):
    line_id = int(tools.obs.rho.argmax())
    board = {
        "constraints": [{"kind": "derate", "line_id": line_id, "pct": 10.0}],
        "vetoes": [],
        "screening_verdicts": [],
        "availability": [],
        "clock": {},
    }
    state = summarize_grid_state(tools.env, tools.obs, board)

    assert state["max_effective_rho"] > state["max_rho"]
    assert state["derate_note"].startswith("weather derate active")
    top = next(line for line in state["top_loaded_lines"] if line["line_id"] == line_id)
    assert top["derate_pct"] == 10.0
    assert top["effective_rho"] > top["rho"]
