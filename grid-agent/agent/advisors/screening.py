"""Post-action N-1 screening advisor backend."""

import time

import numpy as np

from agent.labels import line_label, substation_label


def screen_post_action_env(env, current_obs, action):
    """Apply action to an env copy, then screen every single-line outage."""
    t0 = time.time()
    post_env = env.copy()
    post_obs, _, post_done, _ = post_env.step(action)
    if post_done:
        return {
            "post_action_rho": None,
            "n1_secure": False,
            "post_action_diverged": True,
            "worst_next_contingency": None,
            "screened_outages": 0,
            "insecure_outages": 0,
            "screen_seconds": round(time.time() - t0, 1),
            "baseline_comparison": "candidate action collapses the grid before N-1 screening",
        }

    rows = []
    for line_id in range(post_env.n_line):
        if not post_obs.line_status[line_id]:
            continue
        outage_env = post_env.copy()
        outage = outage_env.action_space({"set_line_status": [(int(line_id), -1)]})
        trip_obs, _, trip_done, _ = outage_env.step(outage)
        if trip_done:
            row = _outage_row(post_env, post_obs, line_id, True, None, None)
        else:
            row = _outage_row(
                post_env,
                post_obs,
                line_id,
                False,
                float(trip_obs.rho.max()),
                int((trip_obs.rho >= 1.0).sum()),
            )
        row["insecure"] = bool(row["diverged"] or (row["post_trip_rho"] or 0.0) >= 1.0)
        rows.append(row)

    insecure = [row for row in rows if row["insecure"]]
    worst = _worst_outage(insecure or rows)
    if worst is not None:
        worst["recovery_action_exists"] = None
        worst["recovery_note"] = "not searched by screen_post_action"
    comparison = _baseline_comparison(env, current_obs, worst)
    return {
        "post_action_rho": round(float(post_obs.rho.max()), 3),
        "n1_secure": not insecure,
        "worst_next_contingency": worst,
        "baseline_comparison": comparison,
        "screened_outages": len(rows),
        "insecure_outages": len(insecure),
        "screen_seconds": round(time.time() - t0, 1),
    }


def _outage_row(env, obs, line_id, diverged, rho, n_overloaded):
    from_sub = int(obs.line_or_to_subid[line_id])
    to_sub = int(obs.line_ex_to_subid[line_id])
    return {
        "line_id": int(line_id),
        "line_label": line_label(
            line_id,
            _sub_label(env, obs, from_sub),
            _sub_label(env, obs, to_sub),
        ),
        "from_sub": from_sub,
        "to_sub": to_sub,
        "diverged": bool(diverged),
        "post_trip_rho": None if rho is None else round(float(rho), 3),
        "n_overloaded_after_trip": n_overloaded,
    }


def _worst_outage(rows):
    if not rows:
        return None
    return max(
        rows,
        key=lambda row: (
            1 if row["diverged"] else 0,
            row["post_trip_rho"] if row["post_trip_rho"] is not None else 0.0,
        ),
    )


def _baseline_comparison(env, current_obs, worst):
    if worst is None:
        return "no in-service post-action lines were available for N-1 screening"
    line_id = int(worst["line_id"])
    if not current_obs.line_status[line_id]:
        return f"line {line_id} is not in service in the current topology"
    baseline_env = env.copy()
    outage = baseline_env.action_space({"set_line_status": [(line_id, -1)]})
    base_obs, _, base_done, _ = baseline_env.step(outage)
    if base_done:
        return f"current topology also diverges after a trip on line {line_id}"
    base_rho = round(float(base_obs.rho.max()), 3)
    base_over = int((base_obs.rho >= 1.0).sum())
    if worst["diverged"]:
        return (
            f"current topology after line {line_id} trip reaches max_rho "
            f"{base_rho} with {base_over} overloaded; post-action topology diverges"
        )
    return (
        f"current topology after line {line_id} trip reaches max_rho {base_rho} "
        f"with {base_over} overloaded; post-action topology reaches max_rho "
        f"{worst['post_trip_rho']}"
    )


def _sub_label(env, obs, sub_id):
    degree = int(
        np.sum(obs.line_or_to_subid == sub_id) + np.sum(obs.line_ex_to_subid == sub_id)
    )
    incident = 0.0
    for line_id, rho in enumerate(obs.rho):
        if int(obs.line_or_to_subid[line_id]) == sub_id:
            incident = max(incident, float(rho))
        if int(obs.line_ex_to_subid[line_id]) == sub_id:
            incident = max(incident, float(rho))
    return substation_label(int(sub_id), degree, incident)
