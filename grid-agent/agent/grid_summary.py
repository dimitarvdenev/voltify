"""Grid state summary helpers for tool responses."""

from __future__ import annotations

from typing import Any

import numpy as np

from agent import config
from agent.labels import line_label, substation_label
from agent.tool_blackboard import compact_blackboard


def degree(env: Any, obs: Any) -> list[int]:
    counts = [0 for _ in range(env.n_sub)]
    for line_id in range(env.n_line):
        counts[int(obs.line_or_to_subid[line_id])] += 1
        counts[int(obs.line_ex_to_subid[line_id])] += 1
    return counts


def incident_rho(env: Any, obs: Any) -> list[float]:
    incident = [0.0 for _ in range(env.n_sub)]
    for line_id, rho in enumerate(obs.rho):
        a = int(obs.line_or_to_subid[line_id])
        b = int(obs.line_ex_to_subid[line_id])
        incident[a] = max(incident[a], float(rho))
        incident[b] = max(incident[b], float(rho))
    return incident


def label_substation(env: Any, obs: Any, sub_id: int) -> str:
    degrees = degree(env, obs)
    incident = incident_rho(env, obs)
    return substation_label(int(sub_id), degrees[int(sub_id)], incident[int(sub_id)])


def line_summary(env: Any, obs: Any, line_id: int) -> dict[str, Any]:
    from_sub = int(obs.line_or_to_subid[line_id])
    to_sub = int(obs.line_ex_to_subid[line_id])
    from_label = label_substation(env, obs, from_sub)
    to_label = label_substation(env, obs, to_sub)
    return {
        "line_id": int(line_id),
        "line_label": line_label(line_id, from_label, to_label),
        "from_sub": from_sub,
        "to_sub": to_sub,
        "rho": round(float(obs.rho[line_id]), 3),
    }


def substation_summary(env: Any, obs: Any, sub_id: int) -> dict[str, Any]:
    return {"sub": int(sub_id), "label": label_substation(env, obs, sub_id)}


def scoped_substations(env: Any, obs: Any, n_hops: int = 1) -> list[int]:
    """Substations at overloaded-line endpoints, grown by n hops."""
    over = np.where(obs.rho > 1.0)[0]
    subs = set()
    for line_id in over:
        subs.add(int(obs.line_or_to_subid[line_id]))
        subs.add(int(obs.line_ex_to_subid[line_id]))
    for _ in range(n_hops):
        grown = set(subs)
        for line_id in range(env.n_line):
            a = int(obs.line_or_to_subid[line_id])
            b = int(obs.line_ex_to_subid[line_id])
            if a in subs:
                grown.add(b)
            if b in subs:
                grown.add(a)
        subs = grown
    return sorted(subs)


def derate_map(board: dict[str, Any]) -> dict[int, float]:
    """line_id -> derate pct from weather constraints on the blackboard."""
    derates = {}
    for item in board.get("constraints", []):
        if item.get("kind") == "derate" and item.get("line_id") is not None:
            derates[int(item["line_id"])] = float(item["pct"])
    return derates


def apply_derates(
    summary: dict[str, Any], derates: dict[int, float]
) -> dict[str, Any]:
    pct = derates.get(summary["line_id"])
    if pct is not None:
        summary["derate_pct"] = pct
        summary["effective_rho"] = round(summary["rho"] / (1.0 - pct / 100.0), 3)
    return summary


def summarize_grid_state(env: Any, obs: Any, board: dict[str, Any]) -> dict[str, Any]:
    rho = obs.rho
    overloaded = np.where(rho > 1.0)[0]
    top = np.argsort(-rho)[: config.TOP_K_LOADED_LINES]
    derates = derate_map(board)
    state = {
        "max_rho": round(float(rho.max()), 3),
        "n_overloaded": int(len(overloaded)),
        "overloaded_lines": [
            apply_derates(line_summary(env, obs, line), derates)
            for line in overloaded
        ],
        "top_loaded_lines": [
            apply_derates(line_summary(env, obs, line), derates) for line in top
        ],
        "disconnected_lines": [int(line) for line in np.where(~obs.line_status)[0]],
        "candidate_scope_subs": scoped_substations(env, obs, n_hops=1),
        "blackboard": compact_blackboard(board),
    }
    if derates:
        effective = [
            float(rho[line]) / (1.0 - pct / 100.0) for line, pct in derates.items()
        ]
        state["max_effective_rho"] = round(max(state["max_rho"], max(effective)), 3)
        state["derate_note"] = (
            "weather derate active: effective_rho is the binding "
            "loading on derated lines, not nameplate rho"
        )
    return state
