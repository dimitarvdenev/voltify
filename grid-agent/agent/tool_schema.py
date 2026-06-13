"""OpenAI tool schema for the grid operation tools."""

from __future__ import annotations

from typing import Any

ToolSchema = list[dict[str, Any]]


TOOLS_SCHEMA: ToolSchema = [
    {
        "type": "function",
        "function": {
            "name": "get_grid_state",
            "description": (
                "Current grid state: worst loadings, overloaded lines, "
                "disconnected lines, and a suggested search scope. All "
                "values from the power-flow solver."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_topology_actions",
            "description": (
                "Simulate every unitary bus-split at the given substations; "
                "returns candidates ranked by resulting max line loading. "
                "Keep scope small (<=8 substations) - the full grid has "
                "72,107 actions and cannot be searched in operator time."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "substations": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": (
                            "Substation ids to search, e.g. candidate_scope_subs "
                            "from get_grid_state."
                        ),
                    },
                    "exclude_substations": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": (
                            "Substations unavailable for switching, e.g. crew on site."
                        ),
                    },
                },
                "required": ["substations"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_redispatch_actions",
            "description": (
                "Escalation step 3 (expensive). Simulate generator redispatch "
                "moves - shifting MW off dispatchable units, auto-balanced "
                "across the fleet - and return candidates ranked by resulting "
                "max line loading. Use when topology switching cannot relieve "
                "the overload. Candidates feed the same simulate -> "
                "check_asset_health -> screen_post_action -> apply_action chain."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_curtailment_actions",
            "description": (
                "Escalation step 4 (last resort, most expensive - EnWG 13a "
                "compensation). Simulate curtailing renewable generation and "
                "return candidates ranked by resulting max line loading. Use "
                "only after switching and redispatch are exhausted. Candidates "
                "feed the same simulate -> check_asset_health -> "
                "screen_post_action -> apply_action chain."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_action",
            "description": (
                "Simulate one candidate from a previous search against the "
                "current state. Solver results only."
            ),
            "parameters": {
                "type": "object",
                "properties": {"action_id": {"type": "string"}},
                "required": ["action_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_asset_health",
            "description": (
                "Ask the Asset Health advisor whether a candidate action is "
                "authorized given equipment condition (partial-discharge "
                "flags, breaker switching-cycle budget). Returns verdict "
                "ok | warn | block. A block requires an operator decision "
                "to override. Use before apply_action."
            ),
            "parameters": {
                "type": "object",
                "properties": {"action_id": {"type": "string"}},
                "required": ["action_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screen_post_action",
            "description": (
                "Ask the Screening advisor to run N-1 screening on the "
                "POST-action topology for a candidate action. Use after "
                "simulate_action and before apply_action. Returns whether "
                "the fix is N-1 secure and the worst next contingency."
            ),
            "parameters": {
                "type": "object",
                "properties": {"action_id": {"type": "string"}},
                "required": ["action_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_action",
            "description": (
                "Apply an action to the REAL grid, then verify stability over "
                "the next steps. Protocol-enforced: requires prior "
                "check_asset_health and screen_post_action for this "
                "action_id; an asset-health block requires an operator "
                "override_veto decision."
            ),
            "parameters": {
                "type": "object",
                "properties": {"action_id": {"type": "string"}},
                "required": ["action_id"],
            },
        },
    },
]
