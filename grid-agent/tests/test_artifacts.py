import json
import os

from agent.artifacts import StepWriter


def test_steps_append_and_persist(tmp_path):
    writer = StepWriter(str(tmp_path))
    writer.add(kind="operator", text="grid status?")
    writer.add(
        kind="tool",
        tool="get_grid_state",
        summary="max rho 1.30, 1 overloaded",
        max_rho=1.30,
        grid_status="overloaded",
    )
    writer.add(
        kind="narration",
        text="Line 177 overloaded...",
        render_zoom="renders/step_2_zoom.html",
    )

    path = os.path.join(str(tmp_path), "steps.json")
    with open(path) as f:
        steps = json.load(f)
    assert [step["step"] for step in steps] == [1, 2, 3]
    assert steps[0]["kind"] == "operator"
    assert steps[1]["tool"] == "get_grid_state"
    assert steps[2]["render_zoom"].endswith("zoom.html")


def test_writer_starts_fresh_each_run(tmp_path):
    StepWriter(str(tmp_path)).add(kind="operator", text="old run")
    StepWriter(str(tmp_path))
    path = os.path.join(str(tmp_path), "steps.json")
    with open(path) as f:
        assert json.load(f) == []
