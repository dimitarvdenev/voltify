"""Random event injector: autonomous grid dynamics.

The base demo grid is static — line loadings (`rho`) only change when the
Ops agent applies an action. Nothing advances the chronic timeseries and
nothing perturbs the network on its own, so between operator turns the
control room is frozen.

This module runs a daemon thread that, on a jittered timer, fires a random
"world event" so the grid lives on its own:

  * `line_trip`   - force-disconnects a random in-service line (a forced
                    outage). Steps the REAL env, so loadings genuinely
                    redistribute and overloads can appear unprompted.
  * `load_drift`  - advances the chronic one step with a do-nothing action,
                    letting scripted load/generation drift move loadings.
  * `weather_shift` - posts a fresh thermal derate constraint to the
                    blackboard (folds into the Ops agent's effective_rho)
                    and narrates it. Does not touch the env.

All env access is serialized with `GridTools.lock`, shared with
`apply_action`, so the injector and the operator loop never step the env
concurrently. Narration uses the same single-shot `advisor_voice` pattern
as the other advisors: one LLM call, deterministic template fallback, so it
stays alive when the model endpoint is down.
"""

import random
import threading

import numpy as np

from agent import config
from agent.advisors.voice import advisor_voice


SYSTEM_PROMPT = """\
You are the Grid Events desk in a transmission control room: the dispatcher
who reports unplanned changes on the network - forced line outages, load
swings, thermal derates rolling in. You do not fix anything; you announce
what just happened so the Operations agent can react. Speak in one or two
terse sentences, like a radio call. State only the facts given.
"""


class EventInjector:
    """Timer-driven random world events against a live GridTools."""

    def __init__(
        self,
        tools,
        writer,
        render_fn=None,
        client=None,
        period=config.INJECTOR_PERIOD_SEC,
        jitter=config.INJECTOR_JITTER_SEC,
        seed=config.INJECTOR_SEED,
    ):
        self.tools = tools
        self.writer = writer
        # render_fn(tag) -> (full_rel, zoom_rel); optional so tests can skip it
        self.render_fn = render_fn
        self.client = client
        self.period = period
        self.jitter = jitter
        self.rng = random.Random(seed)
        self._stop = threading.Event()
        self._thread = None
        # weighted catalog: (handler, weight)
        self._catalog = [
            (self._event_line_trip, 3),
            (self._event_load_drift, 4),
            (self._event_weather_shift, 2),
        ]

    # ---- lifecycle -------------------------------------------------------

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            wait = max(1.0, self.period + self.rng.uniform(-self.jitter, self.jitter))
            if self._stop.wait(wait):
                break
            if self.tools.done:
                break
            try:
                self.fire_once()
            except Exception as exc:  # never let the thread kill the demo
                self.writer.add(
                    kind="event",
                    agent="grid",
                    text=f"(event injector skipped: {type(exc).__name__})",
                )

    # ---- one event -------------------------------------------------------

    def fire_once(self):
        """Pick and apply one random event. Returns the feed entry dict.

        Synchronous and thread-agnostic so it can be driven directly from a
        test without spinning up the timer thread."""
        handler = self._weighted_choice()
        return handler()

    def _weighted_choice(self):
        handlers, weights = zip(*self._catalog)
        return self.rng.choices(handlers, weights=weights, k=1)[0]

    # ---- event handlers --------------------------------------------------

    def _event_line_trip(self):
        live = [
            int(line)
            for line in np.where(self.tools.obs.line_status)[0]
        ]
        if not live:
            return self._event_load_drift()
        line_id = self.rng.choice(live)
        summary = self.tools._line_summary(line_id)
        act = self.tools.env.action_space({"set_line_status": [(line_id, -1)]})
        done, _ = self.tools.step_external(act)
        facts = {
            "event": "forced_line_outage",
            "line_id": line_id,
            "line_label": summary["line_label"],
            "max_rho_after": self._max_rho(),
            "n_overloaded_after": self._n_overloaded(),
        }
        fallback = (
            f"Forced outage on {summary['line_label']} (line {line_id}). "
            f"Loadings redistributing - worst is now {facts['max_rho_after']}, "
            f"{facts['n_overloaded_after']} line(s) over limit."
        )
        return self._emit(facts, fallback, render=True, game_over=done)

    def _event_load_drift(self):
        before = self._max_rho()
        act = self.tools.env.action_space({})
        done, _ = self.tools.step_external(act)
        after = self._max_rho()
        direction = "rising" if after >= before else "easing"
        facts = {
            "event": "load_drift",
            "max_rho_before": before,
            "max_rho_after": after,
            "direction": direction,
            "n_overloaded_after": self._n_overloaded(),
        }
        fallback = (
            f"Demand profile shifting - worst loading {direction} "
            f"{before} -> {after} ({facts['n_overloaded_after']} over limit)."
        )
        return self._emit(facts, fallback, render=True, game_over=done)

    def _event_weather_shift(self):
        rho = self.tools.obs.rho
        line_id = int(np.argsort(-rho)[self.rng.randint(0, 2)])
        summary = self.tools._line_summary(line_id)
        pct = round(self.rng.uniform(4.0, 12.0), 1)
        item = {
            "from": "weather",
            "kind": "derate",
            "line_id": line_id,
            "pct": pct,
            "reason": (
                f"convective heating on {summary['line_label']}; real thermal "
                f"rating {pct}% below nameplate"
            ),
            "ttl_steps": None,
        }
        self.tools.blackboard.append("constraints", item)
        facts = {
            "event": "thermal_derate",
            "line_id": line_id,
            "line_label": summary["line_label"],
            "derate_pct": pct,
            "rho_now": summary["rho"],
        }
        fallback = (
            f"Heat rolling onto {summary['line_label']} (line {line_id}): "
            f"thermal rating now {pct}% below nameplate. Judge its loading "
            "against the derated limit."
        )
        return self._emit(facts, fallback, render=False)

    # ---- emit helpers ----------------------------------------------------

    def _emit(self, facts, fallback, render=False, game_over=False):
        text = advisor_voice(self.client, SYSTEM_PROMPT, facts, fallback)
        entry = {
            "kind": "event",
            "agent": "grid",
            "text": text,
            "grid_status": self._grid_status(),
            "max_rho": self._max_rho(),
        }
        if render and self.render_fn is not None:
            tag = f"event_{len(self.writer.steps)}_{facts['event']}"
            rendered = self.render_fn(tag)
            if rendered:
                entry["render_full"], entry["render_zoom"] = rendered
        self.writer.add(**entry)
        if game_over:
            self.writer.add(
                kind="event",
                agent="grid",
                text="Grid collapsed under the disturbance - run halted.",
                grid_status="overloaded",
                max_rho=self._max_rho(),
            )
            self.stop()
        return entry

    def _max_rho(self):
        return round(float(self.tools.obs.rho.max()), 3)

    def _n_overloaded(self):
        return int((self.tools.obs.rho > 1.0).sum())

    def _grid_status(self):
        return "rescued" if self.tools.obs.rho.max() < 1.0 else "overloaded"
