"""Weather / Environment advisor.

Owns ambient temperature and what it does to real thermal ratings.
Backend: scenarios/weather.json (scripted feed, stand-in values).
Derate math is real: ampacity scales ~ sqrt(Tcond_max - Tambient)
(IEEE-738-style steady-state approximation), so a hot day lowers a
line's true rating below nameplate and the same amps mean a higher
effective loading.
"""

import json
import math
import os

from agent import config
from agent.advisors.voice import advisor_voice


BACKEND_PATH = os.path.join(config.ROOT, "scenarios", "weather.json")

SYSTEM_PROMPT = """\
You are the Weather/Environment advisor in a transmission control room.
You own forecasts and ambient conditions. You do not fix the grid; you
change what counts as safe. You feed derating constraints to the Grid
Operations agent. Speak briefly, like a colleague flagging a hazard.
"""


def load_backend(path=BACKEND_PATH):
    with open(path) as f:
        return json.load(f)


def rating_factor(ambient_c, conductor_max_c, reference_ambient_c):
    """Real ampacity ratio vs nameplate: sqrt((Tmax-Tamb)/(Tmax-Tref))."""
    headroom = conductor_max_c - ambient_c
    reference = conductor_max_c - reference_ambient_c
    if headroom <= 0:
        return 0.0
    return math.sqrt(headroom / reference)


def assess(backend=None):
    """Deterministic assessment: which lines derate, by how much."""
    backend = backend or load_backend()
    factor = rating_factor(
        backend["ambient_c"],
        backend["conductor_max_c"],
        backend["rating_reference_ambient_c"],
    )
    derate_pct = round((1.0 - factor) * 100.0, 1)
    return {
        "station": backend["station"],
        "observed_at": backend.get("observed_at"),
        "ambient_c": backend["ambient_c"],
        "trend_c_per_h": backend.get("trend_c_per_h", 0.0),
        "wind_ms": backend.get("wind_ms"),
        "rating_factor": round(factor, 4),
        "derate_pct": derate_pct,
        "affected_lines": list(backend["overhead_corridor_lines"]),
        "corridor_name": backend.get("corridor_name"),
        "basis": (
            "ampacity ~ sqrt(Tcond_max - Tamb); "
            f"Tcond_max {backend['conductor_max_c']}C, "
            f"reference ambient {backend['rating_reference_ambient_c']}C"
        ),
    }


def constraint_items(assessment):
    """Blackboard constraints the Ops agent must fold into its limits."""
    return [
        {
            "from": "weather",
            "kind": "derate",
            "line_id": int(line_id),
            "pct": assessment["derate_pct"],
            "reason": (
                f"ambient {assessment['ambient_c']}C "
                f"(+{assessment['trend_c_per_h']}C/h), real thermal rating "
                f"{assessment['derate_pct']}% below nameplate"
            ),
            "ttl_steps": None,
        }
        for line_id in assessment["affected_lines"]
    ]


def narrate(assessment, client=None):
    lines = ", ".join(str(line) for line in assessment["affected_lines"])
    corridor = assessment.get("corridor_name") or f"line(s) {lines}"
    fallback = (
        f"Weather: ambient {assessment['ambient_c']}C and rising "
        f"{assessment['trend_c_per_h']}C/h at {assessment['station']}, "
        f"near-calm wind. The {corridor} (line {lines}) derates "
        f"{assessment['derate_pct']}% below nameplate "
        f"({assessment['basis']}). Loadings there must be judged "
        "against the derated limit, not nameplate."
    )
    return advisor_voice(client, SYSTEM_PROMPT, assessment, fallback)


def publish(blackboard, client=None, backend=None):
    """Reactive emitter: assess, post constraints, return feed text."""
    assessment = assess(backend)
    for item in constraint_items(assessment):
        blackboard.append("constraints", item)
    return assessment, narrate(assessment, client)
