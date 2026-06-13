"""Candidate remedial-action search helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from agent import config
from agent.grid_summary import label_substation


@dataclass(frozen=True)
class ActionSearchResult:
    payload: dict[str, Any]
    actions: dict[str, Any]
    meta: dict[str, dict[str, Any]]


def action_effects(env: Any, obs: Any, act: Any, sim_obs: Any) -> tuple[list[int], int]:
    reconnects = [
        int(line)
        for line in range(env.n_line)
        if not obs.line_status[line] and sim_obs.line_status[line]
    ]
    set_bus = act.set_bus
    switching_ops = int(np.sum((set_bus != 0) & (set_bus != obs.topo_vect)))
    return reconnects, switching_ops


def search_topology(
    env: Any,
    obs: Any,
    substations: list[int],
    exclude_substations: list[int] | None = None,
) -> ActionSearchResult:
    subs, skipped = _valid_topology_substations(env, substations, exclude_substations)
    t0 = time.time()
    actions: dict[str, Any] = {}
    meta_by_id: dict[str, dict[str, Any]] = {}
    results = []
    n_tried = 0

    for sub_id in subs:
        found, sub_skipped, tried = _search_topology_substation(env, obs, sub_id)
        skipped.extend(sub_skipped)
        n_tried += tried
        _merge_candidates(found, actions, meta_by_id, results)

    results.sort(key=lambda result: result["simulated_max_rho"])
    payload = {
        "actions_simulated": n_tried,
        "actions_total_grid": total_unitary_actions(),
        "search_seconds": round(time.time() - t0, 1),
        "skipped_substations": skipped,
        "candidates": results[: config.TOP_K_CANDIDATES],
    }
    return ActionSearchResult(payload=payload, actions=actions, meta=meta_by_id)


def _valid_topology_substations(
    env: Any,
    substations: list[int],
    exclude_substations: list[int] | None,
) -> tuple[list[int], list[dict[str, Any]]]:
    excluded = set(exclude_substations or [])
    subs = []
    skipped = []
    for raw_sub in substations:
        sub = int(raw_sub)
        if sub in excluded:
            continue
        if sub < 0 or sub >= env.n_sub:
            skipped.append(
                {
                    "sub": sub,
                    "label": f"Unknown UW {sub}",
                    "reason": "invalid substation id",
                }
            )
            continue
        subs.append(sub)
    return subs, skipped


def _search_topology_substation(
    env: Any, obs: Any, sub_id: int
) -> tuple[list[tuple[str, Any, dict[str, Any]]], list[dict[str, Any]], int]:
    acts = env.action_space.get_all_unitary_topologies_set(
        env.action_space, sub_id=sub_id
    )
    sub_label = label_substation(env, obs, sub_id)
    if len(acts) > config.MAX_ACTIONS_PER_SUB:
        return [], [
            {
                "sub": sub_id,
                "label": sub_label,
                "reason": f"{len(acts)} combos, over cap",
            }
        ], 0

    candidates = []
    n_tried = 0
    for i, act in enumerate(acts):
        sim_obs, _, sim_done, _ = obs.simulate(act)
        n_tried += 1
        if sim_done:
            continue
        action_id = f"a-{sub_id:03d}-{i}"
        reconnects, n_ops = action_effects(env, obs, act, sim_obs)
        candidates.append((
            action_id,
            act,
            _topology_meta(action_id, sub_id, sub_label, sim_obs, reconnects, n_ops),
        ))
    return candidates, [], n_tried


def _topology_meta(
    action_id: str,
    sub_id: int,
    sub_label: str,
    sim_obs: Any,
    reconnects: list[int],
    n_ops: int,
) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "kind": "topology",
        "substation": sub_id,
        "substation_label": sub_label,
        "description": f"bus-split at {sub_label}",
        "simulated_max_rho": round(float(sim_obs.rho.max()), 3),
        "simulated_n_overloaded": int((sim_obs.rho > 1.0).sum()),
        "reconnects_lines": reconnects,
        "switching_ops": n_ops,
        "cost_class": "switching (~free)",
    }


def total_unitary_actions() -> int:
    return 72107


def _merge_candidates(
    candidates: list[tuple[str, Any, dict[str, Any]]],
    actions: dict[str, Any],
    meta_by_id: dict[str, dict[str, Any]],
    results: list[dict[str, Any]],
) -> None:
    for action_id, act, meta in candidates:
        actions[action_id] = act
        meta_by_id[action_id] = meta
        results.append(meta)


def search_redispatch(
    env: Any, obs: Any, max_candidates: int | None = None
) -> ActionSearchResult:
    """Enumerate generator redispatch moves that improve max line loading."""
    t0 = time.time()
    current = round(float(obs.rho.max()), 3)
    producers = [
        gen_id
        for gen_id in range(env.n_gen)
        if env.gen_redispatchable[gen_id] and float(obs.gen_p[gen_id]) > 1.0
    ]
    actions: dict[str, Any] = {}
    meta_by_id: dict[str, dict[str, Any]] = {}
    results = []
    n_tried = 0

    found, tried = _single_redispatch_candidates(env, obs, producers)
    n_tried += tried
    _merge_candidates(found, actions, meta_by_id, results)
    found, tried = _bulk_redispatch_candidate(env, obs, producers)
    n_tried += tried
    _merge_candidates(found, actions, meta_by_id, results)

    payload = _redispatch_payload(results, current, n_tried, t0, max_candidates)
    return ActionSearchResult(payload=payload, actions=actions, meta=meta_by_id)


def search_curtailment(
    env: Any, obs: Any, max_candidates: int | None = None
) -> ActionSearchResult:
    """Enumerate renewable-curtailment moves that improve max line loading."""
    t0 = time.time()
    current = round(float(obs.rho.max()), 3)
    producers = [
        gen_id
        for gen_id in range(env.n_gen)
        if env.gen_renewable[gen_id] and float(obs.gen_p[gen_id]) > 1.0
    ]
    actions: dict[str, Any] = {}
    meta_by_id: dict[str, dict[str, Any]] = {}
    results = []
    n_tried = 0

    found, tried = _single_curtailment_candidates(env, obs, producers)
    n_tried += tried
    _merge_candidates(found, actions, meta_by_id, results)
    found, tried = _bulk_curtailment_candidate(env, obs, producers)
    n_tried += tried
    _merge_candidates(found, actions, meta_by_id, results)

    payload = _curtailment_payload(results, current, n_tried, t0, max_candidates)
    return ActionSearchResult(payload=payload, actions=actions, meta=meta_by_id)


def _single_redispatch_candidates(
    env: Any, obs: Any, producers: list[int]
) -> tuple[list[tuple[str, Any, dict[str, Any]]], int]:
    candidates = []
    n_tried = 0
    for gen_id in producers:
        for delta in _redispatch_moves(env, obs, gen_id):
            act = env.action_space({"redispatch": [(gen_id, delta)]})
            sim_obs, _, sim_done, _ = obs.simulate(act)
            n_tried += 1
            if sim_done:
                continue
            candidates.append(
                _redispatch_candidate(env, obs, gen_id, delta, act, sim_obs)
            )
    return candidates, n_tried


def _redispatch_candidate(
    env: Any, obs: Any, gen_id: int, delta: float, act: Any, sim_obs: Any
) -> tuple[str, Any, dict[str, Any]]:
    action_id = f"rd-{gen_id:02d}-{'dn' if delta < 0 else 'up'}"
    verb = "reduce" if delta < 0 else "raise"
    meta = _gen_action_meta(
        env,
        obs,
        action_id,
        sim_obs,
        "redispatch",
        f"{verb} {_gen_label(env, obs, gen_id)} by {abs(delta):.1f} MW",
        "redispatch (expensive)",
        [int(gen_id)],
        abs(delta),
    )
    return action_id, act, meta


def _bulk_redispatch_candidate(
    env: Any, obs: Any, producers: list[int]
) -> tuple[list[tuple[str, Any, dict[str, Any]]], int]:
    bulk = _bulk_redispatch(env, obs, producers)
    if len(bulk) < 2:
        return [], 0
    act = env.action_space({"redispatch": bulk})
    sim_obs, _, sim_done, _ = obs.simulate(act)
    if sim_done:
        return [], 1
    mw = sum(abs(delta) for _, delta in bulk)
    meta = _gen_action_meta(
        env,
        obs,
        "rd-bulk-dn",
        sim_obs,
        "redispatch",
        f"reduce {len(bulk)} largest dispatchable units by {mw:.1f} MW total",
        "redispatch (expensive)",
        [gen_id for gen_id, _ in bulk],
        mw,
    )
    return [("rd-bulk-dn", act, meta)], 1


def _single_curtailment_candidates(
    env: Any, obs: Any, producers: list[int]
) -> tuple[list[tuple[str, Any, dict[str, Any]]], int]:
    candidates = []
    n_tried = 0
    for gen_id in producers:
        pmax = float(env.gen_pmax[gen_id])
        if pmax <= 0:
            continue
        cur_ratio = float(obs.gen_p[gen_id]) / pmax
        for frac, tag in ((0.5, "half"), (0.0, "off")):
            act = env.action_space(
                {"curtail": [(gen_id, max(0.0, cur_ratio * frac))]}
            )
            sim_obs, _, sim_done, _ = obs.simulate(act)
            n_tried += 1
            if not sim_done:
                candidates.append(
                    _curtailment_candidate(env, obs, gen_id, frac, tag, act, sim_obs)
                )
    return candidates, n_tried


def _curtailment_candidate(
    env: Any,
    obs: Any,
    gen_id: int,
    frac: float,
    tag: str,
    act: Any,
    sim_obs: Any,
) -> tuple[str, Any, dict[str, Any]]:
    action_id = f"ct-{gen_id:02d}-{tag}"
    mw = float(obs.gen_p[gen_id]) * (1.0 - frac)
    meta = _gen_action_meta(
        env,
        obs,
        action_id,
        sim_obs,
        "curtail",
        f"curtail {_gen_label(env, obs, gen_id)} by {mw:.1f} MW "
        f"({'to zero' if frac == 0 else 'by half'})",
        "curtailment (last resort)",
        [int(gen_id)],
        mw,
    )
    return action_id, act, meta


def _bulk_curtailment_candidate(
    env: Any, obs: Any, producers: list[int]
) -> tuple[list[tuple[str, Any, dict[str, Any]]], int]:
    if len(producers) < 2:
        return [], 0
    bulk = [(int(gen_id), 0.0) for gen_id in producers]
    act = env.action_space({"curtail": bulk})
    sim_obs, _, sim_done, _ = obs.simulate(act)
    if sim_done:
        return [], 1
    mw = sum(float(obs.gen_p[gen_id]) for gen_id in producers)
    meta = _gen_action_meta(
        env,
        obs,
        "ct-bulk-off",
        sim_obs,
        "curtail",
        f"curtail all {len(producers)} producing renewables ({mw:.1f} MW)",
        "curtailment (last resort)",
        [int(gen_id) for gen_id in producers],
        mw,
    )
    return [("ct-bulk-off", act, meta)], 1


def _redispatch_moves(env: Any, obs: Any, gen_id: int) -> list[float]:
    moves = []
    down = min(float(env.gen_max_ramp_down[gen_id]), float(obs.gen_p[gen_id]))
    if down > 0.1:
        moves.append(-down)
    up = float(env.gen_max_ramp_up[gen_id])
    if up > 0.1 and float(obs.gen_p[gen_id]) < float(env.gen_pmax[gen_id]) - 0.1:
        moves.append(up)
    return moves


def _redispatch_payload(
    results: list[dict[str, Any]],
    current: float,
    n_tried: int,
    t0: float,
    max_candidates: int | None,
) -> dict[str, Any]:
    candidates = _improving_candidates(results, current)
    return {
        "actions_simulated": n_tried,
        "current_max_rho": current,
        "search_seconds": round(time.time() - t0, 1),
        "candidates": candidates[: max_candidates or config.TOP_K_CANDIDATES],
        "note": (
            "redispatch is expensive vs switching; use only when topology "
            "cannot relieve the overload (escalation step 3). Empty "
            "candidates means redispatch does not relieve this overload."
        ),
    }


def _curtailment_payload(
    results: list[dict[str, Any]],
    current: float,
    n_tried: int,
    t0: float,
    max_candidates: int | None,
) -> dict[str, Any]:
    candidates = _improving_candidates(results, current)
    return {
        "actions_simulated": n_tried,
        "current_max_rho": current,
        "search_seconds": round(time.time() - t0, 1),
        "candidates": candidates[: max_candidates or config.TOP_K_CANDIDATES],
        "note": (
            "curtailment is the most expensive remedial action; use only "
            "after switching and redispatch are exhausted (escalation "
            "step 4). Empty candidates means curtailment does not relieve "
            "this overload."
        ),
    }


def _improving_candidates(
    results: list[dict[str, Any]], current: float
) -> list[dict[str, Any]]:
    candidates = [r for r in results if r["simulated_max_rho"] < current - 1e-6]
    candidates.sort(key=lambda r: r["simulated_max_rho"])
    return candidates


def _bulk_redispatch(env: Any, obs: Any, producers: list[int]) -> list[tuple[int, float]]:
    top = sorted(producers, key=lambda gen_id: float(obs.gen_p[gen_id]), reverse=True)[:5]
    return [
        (int(gen_id), -min(float(env.gen_max_ramp_down[gen_id]), float(obs.gen_p[gen_id])))
        for gen_id in top
        if min(float(env.gen_max_ramp_down[gen_id]), float(obs.gen_p[gen_id])) > 0.1
    ]


def _gen_label(env: Any, obs: Any, gen_id: int) -> str:
    gtype = str(env.gen_type[gen_id])
    sub = int(env.gen_to_subid[gen_id])
    return f"{gtype} unit G-{int(gen_id):02d} @ {label_substation(env, obs, sub)}"


def _gen_action_meta(
    env: Any,
    obs: Any,
    action_id: str,
    sim_obs: Any,
    kind: str,
    description: str,
    cost_class: str,
    generators: list[int],
    mw: float,
) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "kind": kind,
        "description": description,
        "generators": generators,
        "mw_shifted": round(float(mw), 1),
        "simulated_max_rho": round(float(sim_obs.rho.max()), 3),
        "simulated_n_overloaded": int((sim_obs.rho > 1.0).sum()),
        "cost_class": cost_class,
    }
