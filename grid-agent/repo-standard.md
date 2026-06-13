# Agent-Managed Repository Standards (grid-agent)

This document defines the working standards for `grid-agent`. It is meant to
guide both human and agent changes without turning every small patch into a
repo-wide cleanup. New work must follow these standards. Existing violations are
tracked as debt and should be fixed only when they are in scope for the current
change or listed in the active debt section.

## 1. Operating Principles

### Plan-First Changes

* **Planned implementation:** Non-trivial feature work, architecture changes,
  and broad refactors require an approved `docs/PLAN.md` update or a clearly
  named planning note under `docs/`.
* **Lightweight exceptions:** Small bug fixes, tests, docs, and mechanical
  cleanup may proceed without a new phase plan when the intent is obvious and
  the blast radius is narrow.
* **Research before architecture:** Significant design choices require a
  `RESEARCH.md` or equivalent planning note that records trade-offs and rejected
  alternatives.
* **Traceability:** User-facing behavior and milestone work should map back to
  `docs/PRD.md`, `docs/SPEC.md`, `docs/MULTI_AGENT_SPEC.md`, `docs/PLAN.md`,
  or the active demo/benchmark artifacts.

### Scope Discipline

* **Surgical edits:** Modify only files needed for the task. Avoid opportunistic
  formatting, churn, and unrelated refactors.
* **Debt isolation:** Do not make an existing standards violation worse. If a
  touched area already violates a rule, either improve it locally or document
  why fixing it belongs in a separate refactor.
* **Compatibility first:** Public imports, CLI entry points, config formats, and
  session data must remain backward compatible unless a plan explicitly approves
  a breaking change.

## 2. Architecture Standards

### Package Shape

* **Shallow modules:** Prefer a shallow package layout with clear domain modules
  over deeply nested packages.
* **Stable compatibility shims:** When moving public classes or functions, keep
  the old import path as a thin compatibility wrapper until all callers and tests
  are intentionally migrated.
* **Tests mirror behavior:** Tests should be easy to locate from the source they
  cover. Exact one-file-to-one-file mirroring is preferred for new modules, but
  integration and workflow tests may live in broader test files.

### Dependency Direction

* **No circular imports:** Circular imports are a hard failure.
* **Domain logic before UI:** Core grid simulation, advisor, and tool logic must
  not depend on the static web UI or terminal rendering. UI and demo code may
  depend on core logic.
* **Imperative shell:** Isolate I/O, subprocesses, network calls, static file
  serving, Grid2Op environment setup, LLM calls, and filesystem persistence at
  the edges. Keep parsing, scoring, state transitions, and decision logic as
  pure as practical.
* **Explicit integration boundaries:** Long-running loops, plugin callbacks,
  advisor flows, tool execution, and UI inbox/outbox communication should
  communicate through small typed data objects, callbacks, or protocols rather
  than direct mutation of unrelated runtime state.

## 3. Code Standards

### Typing

* **Typed new code:** New and materially changed Python modules should include
  `from __future__ import annotations`.
* **Complete signatures:** Public functions, methods, and complex private
  helpers must have explicit parameter and return types.
* **Avoid untyped plumbing:** Do not introduce new untyped `Any` or
  `dict`-shaped interfaces unless the boundary is genuinely dynamic. Prefer
  Pydantic models, dataclasses, `TypedDict`, `Protocol`, or named aliases.
* **No broad `**kwargs`:** Avoid new `**kwargs` in project-owned APIs. It is
  acceptable only when adapting a third-party framework signature.

### Documentation

* **Intent over narration:** Public modules, classes, and functions should have
  docstrings when their purpose is not obvious from the name and signature.
* **Private helper docs:** Add short docstrings or comments for private helpers
  only when they encode non-obvious behavior, invariants, or compatibility
  constraints.
* **No filler docstrings:** Do not add boilerplate comments that restate the
  code.

### State and Data

* **Immutable by default:** Prefer frozen dataclasses or immutable Pydantic
  models for configuration, descriptors, and value objects.
* **Mutable state is explicit:** Runtime state machines may be mutable, but the
  owner and lifecycle of that state must be obvious.
* **Resource cleanup:** Use async context managers or `AsyncExitStack` when
  coordinating multiple async resources that must be cleaned up together.

## 4. Context Density Targets

These limits keep files reviewable and agent-friendly. Targets guide normal
work. Hard limits block new code unless the current task is explicitly a
decomposition phase or the violation is pre-existing debt.

| Metric | Target | Hard Limit |
| :--- | :--- | :--- |
| File length | < 300 lines | 500 lines |
| Function length | < 30 lines | 50 lines |
| Cyclomatic complexity | < 6 | 10 |
| Module responsibilities | 1 primary domain | 2 domains |

Rules of thumb:

* A file over the target should have a clear reason to stay together.
* A file over the hard limit must not receive unrelated new behavior.
* A long function should usually be split by state transition, I/O boundary, or
  rendering concern, not by arbitrary line count.

## 5. Validation Gates

Run the narrowest useful checks while developing and the full gates before a PR
or phase completion.

* **Bug fixes:** Start with, or add, a failing test that reproduces the bug when
  feasible.
* **Unit and integration tests:** Run the relevant `pytest` subset for every
  code change. Run the full suite before finishing broad refactors.
* **Linting:** `ruff check .` should pass before PR or phase completion.
* **Typing:** `mypy .` should pass before PR or phase completion. If legacy code
  blocks this, document the blocker and do not introduce new typing regressions.
* **Manual smoke tests:** For CLI, static UI, or agent-loop behavior, perform a
  startup or workflow smoke test when automated coverage does not exercise the
  path. For demo changes, run the relevant `make demo`, `make agent`, or
  `make ui` target when feasible.

## 6. Refactor Protocol

Large refactors should proceed in small, reviewable steps:

1. Extract pure helpers or data objects first.
2. Preserve existing public imports with compatibility shims.
3. Move UI, I/O, and stateful coordination behind explicit boundaries.
4. Add focused tests for the extracted unit before deleting old code.
5. Run the existing integration tests after each behavior-preserving stage.

Avoid mixing behavior changes with file movement unless the plan calls that out
explicitly.

## 7. Active Debt

* [ ] **`agent/tools.py`:** Currently about 800 lines — over the hard limit
  (500). It combines Grid2Op environment access, tool registry/execution,
  topology search, simulation, safety checks, and presentation-shaped return
  payloads. It must be decomposed before receiving unrelated feature work.
* [ ] **`agent/render.py`:** Currently about 460 lines — over target (300) and
  close to the hard limit. Keep new behavior out of this file unless directly
  rendering-related; split HTML/data preparation from rendering if it grows.
* [ ] **`agent/advisors/injector.py`:** Currently about 300 lines — at the file
  length target. Split scenario loading, message injection, and timing/runtime
  coordination if it grows.
* [ ] **Typing consistency:** Several existing modules do not yet use
  `from __future__ import annotations`. Add it when touching those modules for
  substantive changes.
* [ ] **Docstring consistency:** Existing private helpers are unevenly
  documented. Improve only where intent or invariants are unclear.
