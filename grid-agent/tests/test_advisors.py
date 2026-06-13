import pytest

from agent.advisors import weather
from agent.advisors.asset_health import AssetHealth
from agent.advisors.injector import EventInjector


def test_weather_rating_factor_math():
    # sqrt((80-34)/(80-25)) = sqrt(46/55)
    factor = weather.rating_factor(34.0, 80.0, 25.0)
    assert factor == pytest.approx(0.9145, abs=0.001)
    assert weather.rating_factor(25.0, 80.0, 25.0) == pytest.approx(1.0)
    assert weather.rating_factor(85.0, 80.0, 25.0) == 0.0


def test_weather_assess_and_constraints():
    assessment = weather.assess()
    assert assessment["ambient_c"] == 34.0
    assert assessment["derate_pct"] == pytest.approx(8.5, abs=0.2)
    assert 177 in assessment["affected_lines"]
    items = weather.constraint_items(assessment)
    assert items[0]["from"] == "weather"
    assert items[0]["kind"] == "derate"
    assert items[0]["line_id"] == 177
    assert items[0]["pct"] == assessment["derate_pct"]


def test_weather_narrate_fallback_grounded():
    assessment = weather.assess()
    text = weather.narrate(assessment, client=None)
    assert "34.0" in text
    assert str(assessment["derate_pct"]) in text


def test_asset_health_blocks_flagged_substation():
    advisor = AssetHealth()
    check = advisor.check_action(67, switching_ops=4)
    assert check["verdict"] == "block"
    assert check["override"] == "human"
    assert any("partial-discharge" in reason for reason in check["reasons"])
    assert check["cycle_budget"]["breaker"] == "B-067"
    assert check["inspection_dispatch_minutes"] == 40


def test_asset_health_clears_healthy_substation():
    advisor = AssetHealth()
    check = advisor.check_action(68, switching_ops=1)
    assert check["verdict"] == "ok"
    assert check["override"] is None
    assert check["cycle_budget"]["ops_remaining_month"] == 34


def test_asset_health_budget_block_and_wear_memory():
    advisor = AssetHealth()
    # hammer substation 68 across incidents: wear accumulates per run
    for _ in range(8):
        advisor.record_switch(68, 4)
    record = advisor.record_for(68)
    assert record["ops_used_month"] == 6 + 32
    check = advisor.check_action(68, switching_ops=4)
    assert check["verdict"] == "block"
    assert any("budget" in reason for reason in check["reasons"])


def test_asset_health_warn_near_budget():
    advisor = AssetHealth()
    advisor.record_switch(68, 28)  # 6 + 28 used -> 6 remaining
    check = advisor.check_action(68, switching_ops=4)
    assert check["verdict"] == "warn"


def test_check_asset_health_tool_vetoes_best_fix(tools, arc):
    res = tools.search_topology_actions(arc["scoped_subs"])
    best = res["candidates"][0]
    assert best["substation"] == arc["rescue_substation"]  # 67, solver-true
    check = tools.check_asset_health(best["action_id"])
    assert check["verdict"] == "block"
    assert "narration" in check and best["action_id"] in check["narration"]
    veto = tools.blackboard.read()["vetoes"][-1]
    assert veto["from"] == "asset_health"
    assert veto["action_id"] == best["action_id"]
    assert veto["override"] == "human"
    # the proven second-best at substation 68 passes asset health
    second = next(
        candidate for candidate in res["candidates"] if candidate["substation"] == 68
    )
    assert tools.check_asset_health(second["action_id"])["verdict"] == "ok"


class _FakeWriter:
    """Minimal StepWriter stand-in: collects feed entries in memory."""

    def __init__(self):
        self.steps = []

    def add(self, **step):
        step["step"] = len(self.steps) + 1
        self.steps.append(step)


@pytest.fixture(scope="module")
def mutable_tools():
    """Fresh GridTools the injector may step (the shared `tools` fixture is
    session-scoped and read-only). The blackboard is file-backed at a fixed
    path shared with every other test, so snapshot and restore it to keep
    injected constraints from leaking across test files."""
    from agent.tools import GridTools

    tools = GridTools()
    saved = tools.blackboard.read()
    yield tools
    tools.blackboard.write(saved)


def _injector(tools):
    return EventInjector(
        tools, _FakeWriter(), render_fn=None, client=None, seed=7
    )


def test_injector_weather_shift_posts_derate(mutable_tools):
    inj = _injector(mutable_tools)
    before = len(mutable_tools.blackboard.read()["constraints"])
    entry = inj._event_weather_shift()
    constraints = mutable_tools.blackboard.read()["constraints"]
    assert len(constraints) == before + 1
    added = constraints[-1]
    assert added["from"] == "weather"
    assert added["kind"] == "derate"
    assert 4.0 <= added["pct"] <= 12.0
    assert entry["kind"] == "event" and entry["agent"] == "grid"
    assert inj.writer.steps[-1]["text"] == entry["text"]


def test_injector_line_trip_disconnects_a_line(mutable_tools):
    inj = _injector(mutable_tools)
    live_before = int(mutable_tools.obs.line_status.sum())
    entry = inj._event_line_trip()
    live_after = int(mutable_tools.obs.line_status.sum())
    # either a line dropped out, or the disturbance ended the episode
    assert live_after < live_before or mutable_tools.done
    assert entry["kind"] == "event" and entry["agent"] == "grid"
    assert "max_rho" in entry
    assert inj.writer.steps[-1]["kind"] == "event"


def test_injector_load_drift_advances_env(mutable_tools):
    inj = _injector(mutable_tools)
    entry = inj._event_load_drift()
    assert entry["kind"] == "event" and entry["agent"] == "grid"
    assert isinstance(entry["max_rho"], float)
    assert inj.writer.steps[-1]["kind"] == "event"


def test_injector_fire_once_records_one_feed_event(mutable_tools):
    inj = _injector(mutable_tools)
    n_before = len(inj.writer.steps)
    entry = inj.fire_once()
    assert entry["kind"] == "event"
    assert len(inj.writer.steps) == n_before + 1


def test_get_grid_state_folds_weather_derate(tools, arc):
    board_before = tools.blackboard.read()
    try:
        weather.publish(tools.blackboard, client=None)
        state = tools.get_grid_state()
        crisis = next(
            line
            for line in state["overloaded_lines"]
            if line["line_id"] == arc["crisis_line_id"]
        )
        assert crisis["derate_pct"] == pytest.approx(8.5, abs=0.2)
        assert crisis["effective_rho"] == pytest.approx(
            crisis["rho"] / (1 - crisis["derate_pct"] / 100), abs=0.01
        )
        assert state["max_effective_rho"] > state["max_rho"]
        assert "derate_note" in state
    finally:
        tools.blackboard.write(board_before)
