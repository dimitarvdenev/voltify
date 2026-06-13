"""Compact blackboard payloads for tool responses."""

from __future__ import annotations

from typing import Any


def screening_blackboard_item(result: dict[str, Any]) -> dict[str, Any]:
    worst = result.get("worst_next_contingency") or {}
    return {
        "from": "screening",
        "kind": "post_action_n1",
        "action_id": result.get("action_id"),
        "n1_secure": result.get("n1_secure"),
        "n1_not_worse": result.get("n1_not_worse"),
        "post_action_rho": result.get("post_action_rho"),
        "worst_next_contingency": {
            "line_id": worst.get("line_id"),
            "post_trip_rho": worst.get("post_trip_rho"),
            "diverged": worst.get("diverged"),
        },
        "screened_outages": result.get("screened_outages"),
        "insecure_outages": result.get("insecure_outages"),
        "reason": result.get("baseline_comparison"),
    }


def compact_blackboard(board: dict[str, Any]) -> dict[str, Any]:
    latest_screening = None
    if board["screening_verdicts"]:
        latest = board["screening_verdicts"][-1]
        latest_screening = {
            "action_id": latest.get("action_id"),
            "n1_secure": latest.get("n1_secure"),
            "n1_not_worse": latest.get("n1_not_worse"),
            "post_action_rho": latest.get("post_action_rho"),
            "worst_next_contingency": latest.get("worst_next_contingency"),
            "insecure_outages": latest.get("insecure_outages"),
        }
    latest_constraint = None
    if board["constraints"]:
        item = board["constraints"][-1]
        latest_constraint = {
            "from": item.get("from"),
            "kind": item.get("kind"),
            "line_id": item.get("line_id"),
            "sub": item.get("sub"),
            "pct": item.get("pct"),
        }
    latest_veto = None
    if board["vetoes"]:
        item = board["vetoes"][-1]
        latest_veto = {
            "from": item.get("from"),
            "action_id": item.get("action_id"),
            "level": item.get("level"),
            "override": item.get("override"),
            "substation": item.get("substation"),
        }
    return {
        "constraint_count": len(board["constraints"]),
        "latest_constraint": latest_constraint,
        "veto_count": len(board["vetoes"]),
        "latest_veto": latest_veto,
        "latest_screening_verdict": latest_screening,
        "availability_count": len(board["availability"]),
        "clock": board["clock"],
    }
