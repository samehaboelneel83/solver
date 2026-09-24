"""A run, told as GenUI events: the pipeline is the agent (Phase 1).

The solve pipeline already does, in order, what an optimization agent does
-- takes the job, builds the model, chooses a solver, solves, works the
answer up -- and records each step as a `run_event`. This turns those
records into the GenUI protocol (`protocol.json`): the agent's state, a few
sentences in its words, and components that are created as skeletons,
hydrate as facts arrive and complete when their part is done.

Every number comes from the run's own records; nothing is estimated to make
a card look busy. A step the pipeline does not take (planning, generating
expressions) is never announced. A language model can later emit the same
events; the browser would not know the difference.

Pure: `feed` takes one recorded event, `settle` the run's final record, and
each returns the GenUI events to send. The stream (`app.api.genui`) does
the I/O.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROTOCOL: dict[str, Any] = {
    k: v for k, v in json.loads(Path(__file__).with_name("protocol.json").read_text(encoding="utf-8")).items()
    if not k.startswith("//")
}
COMPONENT_TYPES = frozenset(PROTOCOL["componentTypes"])
AGENT_STATES = frozenset(PROTOCOL["agentStates"])
EVENTS = frozenset(PROTOCOL["events"])

#: The steps the timeline shows, in order: the agent states this pipeline
#: actually passes through.
STEPS = ["submitting_job", "understanding", "building_model", "selecting_solver", "solving", "post_processing", "complete"]

_ENDED_WELL = {"optimal", "feasible"}


def _gap(objective, bound) -> float | None:
    if objective is None or bound is None:
        return None
    objective, bound = float(objective), float(bound)
    if objective == bound:
        return 0.0
    return abs(objective - bound) / max(abs(objective), 1e-9)


class Translator:
    def __init__(self, run_id: int, *, status: str, time_limit_s: float | None, spatial: bool = False) -> None:
        self.run_id = run_id
        # A run whose model keeps groups connected over units with a shape:
        # its answer is also a map (GET /runs/{id}/map).
        self.spatial = spatial
        self.time_limit = time_limit_s
        self.state: str | None = None
        self.done: list[str] = []
        self.created: set[str] = set()
        self.completed: set[str] = set()
        self.last_progress: dict[str, Any] | None = None
        self.initial_status = status

    # -- helpers ----------------------------------------------------------

    def _id(self, name: str) -> str:
        return f"run-{self.run_id}-{name}"

    def _event(self, event: str, **body: Any) -> dict[str, Any]:
        assert event in EVENTS, event
        return {"event": event, **body}

    def _enter(self, state: str) -> list[dict]:
        assert state in AGENT_STATES, state
        if state == self.state:
            return []
        if self.state is not None and self.state not in self.done:
            self.done.append(self.state)
        self.state = state
        return [
            self._event("agent.state", state=state),
            self._event("component.data", id=self._id("timeline"),
                        data={"steps": STEPS, "current": state, "done": list(self.done)}),
        ]

    def _create(self, name: str, kind: str, state: str = "skeleton", **extra: Any) -> list[dict]:
        assert kind in COMPONENT_TYPES, kind
        if name in self.created:
            return []
        self.created.add(name)
        return [self._event("component.created", component={"id": self._id(name), "type": kind, "state": state, **extra})]

    def _data(self, name: str, data: dict, state: str = "hydrating") -> list[dict]:
        return [
            self._event("component.updated", id=self._id(name), state=state),
            self._event("component.data", id=self._id(name), data=data),
        ]

    def _complete(self, name: str) -> list[dict]:
        if name not in self.created or name in self.completed:
            return []
        self.completed.add(name)
        return [self._event("component.completed", id=self._id(name))]

    def _say(self, text: str) -> dict:
        return self._event("agent.message", text=text)

    # -- the stream -------------------------------------------------------

    def opening(self) -> list[dict]:
        """What is shown before any event: the job is in, the plan is on screen."""
        out = [self._say(f"Run {self.run_id} is queued; a worker will take it.")]
        out += self._create("timeline", "timeline", state="interactive", props={"title": "What the solver is doing"})
        out += self._enter("submitting_job")
        return out

    def feed(self, kind: str, payload: dict[str, Any]) -> list[dict]:
        if kind == "stage":
            return self._stage(payload.get("stage"), payload)
        if kind in ("incumbent", "bound"):
            return self._progress(payload)
        if kind == "log":
            out = self._create("log", "solver-log", state="hydrating", props={"title": "Solver log"})
            return out + [self._event("component.data", id=self._id("log"),
                                      data={"append": [str(payload.get("line") or payload.get("text") or "")]})]
        return []

    def _stage(self, stage: str | None, facts: dict) -> list[dict]:
        out: list[dict] = []
        if stage == "started":
            out += self._enter("understanding")
            out.append(self._say("A worker took the run and is reading the model against its frozen data."))
            # The model's card, as a skeleton while it is read and built.
            out += self._create("model", "model-summary", props={"title": "The model"})
        elif stage == "compiling":
            out += self._enter("building_model")
        elif stage == "compiled":
            out += self._create("model", "model-summary", props={"title": "The model"})
            out += self._enter("building_model")
            fingerprint = facts.get("fingerprint") or {}
            out += self._data("model", {
                "modelClass": facts.get("model_class"),
                "variables": facts.get("variables"),
                "constraints": facts.get("rules"),
                "fingerprint": fingerprint,
            }, state="hydrated")
            out += self._complete("model")
            out.append(self._say(
                f"The model is {facts.get('model_class')}: {facts.get('variables')} decisions, "
                f"{facts.get('rules')} rule instances."
            ))
            out += self._enter("selecting_solver")
            out += self._create("solver", "solver-status", props={"title": "Solver"})
        elif stage == "chosen":
            out += self._enter("selecting_solver")
            out += self._create("solver", "solver-status", props={"title": "Solver"})
            out += self._data("solver", {"solver": facts.get("solver"), "why": facts.get("why"),
                                         "modelClass": facts.get("model_class")}, state="hydrated")
        elif stage == "probing":
            # The probe race (app.solve.race): the choice is being tried, not assumed.
            out += self._enter("selecting_solver")
            solvers = ", ".join(facts.get("solvers") or [])
            out.append(self._say(f"Trying {solvers} for {facts.get('seconds', 0):g} s each; the best goes on."))
        elif stage == "solving":
            out += self._create("solver", "solver-status", props={"title": "Solver"})
            if "solver" not in self.completed:
                out += self._data("solver", {"solver": facts.get("solver"), "timeLimit": facts.get("time_limit_s")},
                                  state="hydrated")
            out += self._complete("solver")
            self.time_limit = facts.get("time_limit_s") or self.time_limit
            out += self._enter("solving")
            out += self._create("progress", "solver-progress", props={"title": "Optimization", "timeLimit": self.time_limit, "runId": self.run_id})
        elif stage == "post_processing":
            out += self._complete("progress")
            out += self._enter("post_processing")
        # `settled` is the stream's to act on: it needs the run's record (`settle`).
        return out

    def _progress(self, payload: dict) -> list[dict]:
        out = self._create("progress", "solver-progress", props={"title": "Optimization", "timeLimit": self.time_limit, "runId": self.run_id})
        merged = {**(self.last_progress or {}), **{k: v for k, v in payload.items() if k in ("t", "objective", "bound")}}
        self.last_progress = merged
        data = {"elapsed": merged.get("t"), "objective": merged.get("objective"), "bound": merged.get("bound"),
                "gap": _gap(merged.get("objective"), merged.get("bound"))}
        if self.time_limit:
            # Of the time allowed -- the one progress a solver cannot fake.
            data["timeShare"] = min(1.0, float(merged.get("t") or 0) / float(self.time_limit))
        return out + self._data("progress", data)

    def settle(self, record: dict[str, Any]) -> list[dict]:
        """The run's final record: status, objective, bound, gap, optimality,
        wall time, solver, error."""
        status = record.get("status")
        out = self._complete("progress")
        out += self._enter("hydrating_ui")
        summary = {
            "status": status,
            "objective": record.get("objective"),
            "bound": record.get("best_bound"),
            "gap": record.get("gap"),
            "optimality": record.get("optimality"),
            "wallTime": record.get("wall_time_s"),
            "solver": record.get("solver"),
            "error": record.get("error"),
            "runId": self.run_id,
        }
        failed = status not in _ENDED_WELL
        out += self._create("summary", "optimization-summary", props={"title": "Result"})
        out += self._data("summary", summary, state="error" if status == "error" else "hydrated")
        if not failed:
            out += self._create("objective", "metric", props={"label": "Objective", "format": "number"})
            out += self._data("objective", {"value": record.get("objective")}, state="hydrated")
            out += self._create("gap", "metric", props={"label": "Gap", "format": "percent"})
            out += self._data("gap", {"value": record.get("gap")}, state="hydrated")
            out += self._create("time", "metric", props={"label": "Time", "format": "seconds"})
            out += self._data("time", {"value": record.get("wall_time_s")}, state="hydrated")
            for name in ("objective", "gap", "time"):
                out += self._complete(name)
            if self.spatial:
                # The map reads the stored answer itself, so it is hydrated
                # from the start: nothing is drawn from a guess mid-solve.
                out += self._create("map", "spatial-map", state="hydrated",
                                    props={"title": "The partition", "runId": self.run_id},
                                    data={"source": "run", "runId": self.run_id})
                out += self._complete("map")
        out += self._complete("summary")
        if status == "optimal":
            out.append(self._say(f"Solved: {record.get('objective')}, proven the best "
                                 f"({record.get('optimality') or 'global'})."))
            out += self._enter("complete")
        elif status == "feasible":
            out.append(self._say("An answer was found, but not proven the best within the time allowed."))
            out += self._enter("warning")
        elif status == "cancelled":
            out.append(self._say("The run was stopped before it found an answer."))
            out += self._enter("warning")
        else:
            reason = record.get("error") or {"infeasible": "no answer satisfies every rule",
                                             "unbounded": "the goal can improve without limit"}.get(status, status)
            out.append(self._say(f"The run ended {status}: {reason}."))
            out += self._enter("error")
        out += self._complete("timeline")
        return out
