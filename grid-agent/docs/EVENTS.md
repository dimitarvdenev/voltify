# EVENTS — handoff

Two independent event streams. Don't confuse them.

- **Feed** (`artifacts/run/steps.json`) — narration for humans; the UI polls it
  every 1s and renders one lane per agent.
- **Blackboard** (`artifacts/run/blackboard.json`) — machine state the Ops
  agent reads back and the apply-guard enforces on. Not rendered directly.

The same advisor often writes both (e.g. an asset block → a `veto` feed step
AND a `vetoes` blackboard entry).

## Feed events (steps.json)

The LLM loop (`llm.py`) emits only **two raw kinds**: `narration` and `tool`.
Everything else is relabeled in `main.py`'s `on_event` by inspecting the tool
name. Agent defaults to `ops` (`artifacts.py:_agent_for_step`) unless overridden.

| kind | agent | source | trigger |
|------|-------|--------|---------|
| `narration` | ops | `llm.py:65,82,108`; `main.py:82` | model text (final / alongside tools / iter-limit); plus the "Connected to grid" open |
| `tool` | ops | `llm.py:89` | one per tool call the model issues |
| `operator` | operator | `main.py:153` | operator message from inbox/stdin |
| `constraint` | weather | `main.py:96` | session-open weather bulletin (reactive, before loop) |
| `verdict` | screening / asset_health | `main.py:118,123` (relabel) | a `tool` event whose tool is `screen_post_action` or `check_asset_health` (ok/warn) |
| `veto` | asset_health | `main.py:123` via `_asset_feed` | `check_asset_health` result with `verdict=="block"` |

Flow:

```
llm.run_loop → emit(kind, payload) → main.on_event(kind, payload)
   kind=="tool" → inspect payload["tool"]:
        screen_post_action → agent=screening,   kind=verdict
        check_asset_health → agent=asset_health, kind=verdict | veto
        apply_action       → also attach grid render
   → writer.add(**entry) → append steps.json (atomic tmp+rename)
```

`verdict` and `veto` are **derived** kinds: the loop only knows `tool`; main
re-tags by tool name. UI matches CSS on `msg <kind> <agent>` for the lanes.

## Blackboard events (blackboard.json)

`blackboard.append(key, item)`:

| key | written by | when |
|-----|-----------|------|
| `constraints` | `weather.py:107` | derate item at session open |
| `vetoes` | `tools.py:328` | `check_asset_health` block |
| `screening_verdicts` | `tools.py:351` | every `screen_post_action` |
| `decisions` | `main.py:44` | operator sends structured `{"kind":"decision",...}` |
| `availability`, `clock` | — | reserved for Field agent (Scenario 4), unused |

Loop-back: Ops reads the blackboard via `get_grid_state` →
`_compact_blackboard` (derates fold into `effective_rho`; vetoes + latest
screening verdict surface). The apply-guard reads `decisions` via
`_operator_override` — an asset block clears only on an `override_veto`
decision for that `action_id`.

## Adding a new event kind

1. If it comes from a tool: relabel in `main.py:on_event` by tool name.
2. If reactive (like weather): `writer.add(kind=..., agent=...)` directly +
   `blackboard.append(...)` if Ops must consume it.
3. Add a UI lane: CSS selector `.<kind>.<agent>` / `.narration.<agent>` in
   `ui/index.html`, plus a `::before` label.
