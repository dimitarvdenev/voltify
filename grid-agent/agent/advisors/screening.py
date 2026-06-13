"""Post-action N-1 screening advisor backend.

The verdict that matters on a stressed grid is not absolute N-1 security
(the baseline itself may already be fragile) but whether the proposed fix
INTRODUCES fragilities: contingencies the current topology absorbs that
the post-fix topology cannot. n1_secure stays absolute; n1_not_worse is
the apply gate.
"""

import time

import numpy as np

from agent.labels import line_label, substation_label


def screen_topology(env, obs):
    """Screen every in-service single-line outage against this topology."""
    rows = []
    for line_id in range(env.n_line):
        if not obs.line_status[line_id]:
            continue
        outage_env = env.copy()
        outage = outage_env.action_space({"set_line_status": [(int(line_id), -1)]})
        trip_obs, _, trip_done, _ = outage_env.step(outage)
        if trip_done:
            row = _outage_row(env, obs, line_id, True, None, None)
        else:
            row = _outage_row(
                env,
                obs,
                line_id,
                False,
                float(trip_obs.rho.max()),
                int((trip_obs.rho >= 1.0).sum()),
            )
        row["insecure"] = bool(row["diverged"] or (row["post_trip_rho"] or 0.0) >= 1.0)
        rows.append(row)
    return rows


def screen_post_action_env(env, current_obs, action, baseline_rows=None):
    """Apply action to an env copy, screen all outages, compare to baseline.

    Returns (result, baseline_rows); pass baseline_rows back in to skip
    re-screening the unchanged current topology.
    """
    t0 = time.time()
    post_env = env.copy()
    post_obs, _, post_done, _ = post_env.step(action)
    if post_done:
        return _post_action_diverged_result(t0), baseline_rows

    rows = screen_topology(post_env, post_obs)
    if baseline_rows is None:
        baseline_rows = screen_topology(env, current_obs)
    comparison = _compare_screening_rows(rows, baseline_rows)
    return _post_action_result(post_obs, rows, comparison, t0), baseline_rows


def _post_action_diverged_result(t0):
    return {
        "post_action_rho": None,
        "n1_secure": False,
        "n1_not_worse": False,
        "post_action_diverged": True,
        "worst_next_contingency": None,
        "new_fragilities": [],
        "screened_outages": 0,
        "insecure_outages": 0,
        "screen_seconds": round(time.time() - t0, 1),
        "baseline_comparison": (
            "candidate action collapses the grid before N-1 screening"
        ),
    }


def _compare_screening_rows(rows, baseline_rows):
    base_insecure_ids = {row["line_id"] for row in baseline_rows if row["insecure"]}
    post_insecure = [row for row in rows if row["insecure"]]
    new_fragilities = [
        row for row in post_insecure if row["line_id"] not in base_insecure_ids
    ]
    post_secure_ids = {row["line_id"] for row in rows if not row["insecure"]}
    resolved = sorted(base_insecure_ids & post_secure_ids)
    worst = _worst_contingency(new_fragilities, post_insecure, rows, base_insecure_ids)
    return {
        "base_insecure_ids": base_insecure_ids,
        "post_insecure": post_insecure,
        "new_fragilities": new_fragilities,
        "resolved": resolved,
        "worst": worst,
        "text": _comparison_text(new_fragilities, post_insecure, resolved, worst),
    }


def _worst_contingency(new_fragilities, post_insecure, rows, base_insecure_ids):
    worst = _worst_outage(new_fragilities or post_insecure or rows)
    if worst is not None:
        worst = dict(worst)
        worst["recovery_action_exists"] = None
        worst["recovery_note"] = "not searched by screen_post_action"
        worst["fragility_is_new"] = worst["line_id"] not in base_insecure_ids
    return worst


def _comparison_text(new_fragilities, post_insecure, resolved, worst):
    if new_fragilities:
        return (
            f"fix INTRODUCES {len(new_fragilities)} fragilit"
            f"{'y' if len(new_fragilities) == 1 else 'ies'} the current "
            f"topology absorbs (worst: line {worst['line_id']}); "
            f"{len(post_insecure) - len(new_fragilities)} further insecure "
            "outages are pre-existing"
        )
    if post_insecure:
        return (
            f"all {len(post_insecure)} insecure outages are pre-existing in "
            "the current stressed topology; the fix does not worsen N-1"
            + (f" and resolves {len(resolved)} of them" if resolved else "")
        )
    return "post-action topology is fully N-1 secure"


def _post_action_result(post_obs, rows, comparison, t0):
    new_fragilities = comparison["new_fragilities"]
    post_insecure = comparison["post_insecure"]
    return {
        "post_action_rho": round(float(post_obs.rho.max()), 3),
        "n1_secure": not post_insecure,
        "n1_not_worse": not new_fragilities,
        "worst_next_contingency": comparison["worst"],
        "new_fragilities": [_fragility_summary(row) for row in new_fragilities[:3]],
        "baseline_insecure_outages": len(comparison["base_insecure_ids"]),
        "resolved_fragilities": len(comparison["resolved"]),
        "baseline_comparison": comparison["text"],
        "screened_outages": len(rows),
        "insecure_outages": len(post_insecure),
        "screen_seconds": round(time.time() - t0, 1),
    }


def _fragility_summary(row):
    return {
        "line_id": row["line_id"],
        "line_label": row["line_label"],
        "diverged": row["diverged"],
        "post_trip_rho": row["post_trip_rho"],
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
