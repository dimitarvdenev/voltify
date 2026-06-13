from agent.tool_blackboard import compact_blackboard, screening_blackboard_item


def test_screening_blackboard_item_keeps_compact_verdict_fields():
    item = screening_blackboard_item(
        {
            "action_id": "a-067-3",
            "n1_secure": False,
            "n1_not_worse": True,
            "post_action_rho": 0.83,
            "worst_next_contingency": {
                "line_id": 12,
                "line_label": "Line 12",
                "post_trip_rho": 1.2,
                "diverged": False,
            },
            "screened_outages": 117,
            "insecure_outages": [12],
            "baseline_comparison": "resolved most baseline fragilities",
        }
    )

    assert item == {
        "from": "screening",
        "kind": "post_action_n1",
        "action_id": "a-067-3",
        "n1_secure": False,
        "n1_not_worse": True,
        "post_action_rho": 0.83,
        "worst_next_contingency": {
            "line_id": 12,
            "post_trip_rho": 1.2,
            "diverged": False,
        },
        "screened_outages": 117,
        "insecure_outages": [12],
        "reason": "resolved most baseline fragilities",
    }


def test_compact_blackboard_reports_counts_and_latest_items():
    compact = compact_blackboard(
        {
            "constraints": [
                {"from": "weather", "kind": "derate", "line_id": 4, "pct": 7.5}
            ],
            "vetoes": [
                {
                    "from": "asset_health",
                    "action_id": "a-001-0",
                    "level": "block",
                    "override": "operator",
                    "substation": 1,
                }
            ],
            "screening_verdicts": [
                {
                    "action_id": "a-067-3",
                    "n1_secure": True,
                    "n1_not_worse": True,
                    "post_action_rho": 0.83,
                    "worst_next_contingency": {"line_id": 12},
                    "insecure_outages": [],
                }
            ],
            "availability": [{"sub": 67}],
            "clock": {"step": 3},
        }
    )

    assert compact["constraint_count"] == 1
    assert compact["latest_constraint"]["line_id"] == 4
    assert compact["veto_count"] == 1
    assert compact["latest_veto"]["action_id"] == "a-001-0"
    assert compact["latest_screening_verdict"]["action_id"] == "a-067-3"
    assert compact["availability_count"] == 1
    assert compact["clock"] == {"step": 3}
