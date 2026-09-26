"""Solvers added without changing the platform (queue R41): adapters, each a folder with a manifest.

Any native solver -- Gurobi, Xpress, CPLEX, COPT, a research code, a customer's own heuristic --
joins the registry (`app.solve.backends.REGISTRY`) as an ordinary backend, chosen by the same
policy as the built-ins. The platform buys and ships nothing: the solver and its licence are the
customer's, in their image or a mounted volume. An adapter is a folder holding `adapter.toml`:

    name = "cbc"                  # lower-case, not a built-in's name
    kind = "ortools-engine"       # or "command-line", or "python"
    version = "2.10"
    proves = "global"             # what its `optimal` means: global, local or approximate
    classes = ["IP", "LP", "MILP", "trivial"]   # optional: the kind's ceiling by default
    provides = ["linear", "integral", ...]     # optional, likewise; never beyond the ceiling
    rank = 50                     # optional; built-ins are 0-7
    note = "..."

    [engine]                      # kind = "ortools-engine"
    engine = "CBC"                # an OR-Tools engine: CBC, SCIP, GUROBI, XPRESS, CPLEX, ...

    [command]                     # kind = "command-line"
    executable = "cbc"
    args = ["{model}", "sec", "{time_limit}", "solve", "solu", "{solution}"]
    solution = "sol"              # the format of the file it writes
    infeasible_exit_codes = []    # optional
    unbounded_exit_codes = []     # optional

    [python]                      # kind = "python"
    module = "adapter.py"         # a file in the folder
    function = "solve"            # the built-ins' signature

    [environment]                 # optional: set for the solve (GUROBI_HOME, XPRESSDIR, ...)
    GUROBI_HOME = "/opt/gurobi"

**The three kinds.** An `ortools-engine` adapter is a manifest only: the model goes through the
same translation as the built-in `milp` backend to an engine OR-Tools loads at run time -- which
is how Gurobi, Xpress and CPLEX arrive, their libraries found where the vendor installed them. A
`command-line` adapter is a program: the model is written as MPS (variables `v0, v1, ...`), the
program run with the manifest's arguments -- `{model}`, `{solution}`, `{time_limit}`, `{threads}`,
`{gap}`, `{seed}`, `{adapter_dir}` -- and the solution file read back. A `python` adapter is a
function with the built-ins' signature, for full control.

**What an adapter may claim** is bounded by its kind. The two linear kinds carry exactly what the
`milp` backend's translation carries, so a manifest cannot claim a quadratic rule an MPS file
cannot hold; a `python` adapter may claim anything some built-in provides, and nothing unknown.

**Nothing an adapter does stops the platform.** A manifest that cannot be read or that claims
something it may not is skipped, with the reason kept in `SKIPPED` (the Solvers page shows it).
An adapter is never chosen automatically until the conformance kit (queue R43) has passed it:
until then it runs only when asked for by name.

**Where from.** `SOLVER_ADAPTERS_DIR`: folders, separated by the path separator, each holding one
folder per adapter (default `/opt/solver/adapters`). Loaded once per process -- the API, the worker
and each sandboxed solve read the same folders, so they agree; a change takes effect on restart.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import tempfile
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.solve.compile import Compiled
from app.solve.result import Solution

#: The folders adapters are read from when `SOLVER_ADAPTERS_DIR` is not set.
DEFAULT_DIRS = "/opt/solver/adapters"
#: The rank an adapter takes when its manifest names none: after every built-in.
DEFAULT_RANK = 50
KINDS = ("ortools-engine", "command-line", "python")
_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
#: What a command-line solver is given beyond its time limit before it is stopped.
GRACE_S = 5.0
#: The solution file formats a command-line adapter may name.
SOLUTION_FORMATS = ("sol",)

#: Manifests that were not loaded, and why: [{"folder": ..., "reason": ...}].
SKIPPED: list[dict[str, str]] = []


class AdapterRefused(ValueError):
    """A manifest that cannot be loaded. The message says why, for the Solvers page."""


class AdapterFailed(RuntimeError):
    """An added solver that failed while solving: the run records this message as its error
    (with any licence scrubbed from it, `app.solve.sandbox.scrubbed`)."""


@dataclass(frozen=True)
class Manifest:
    name: str
    kind: str
    version: str
    proves: str
    classes: frozenset[str]
    provides: frozenset[str]
    rank: int
    note: str
    folder: Path
    engine: dict[str, Any] = field(default_factory=dict)
    command: dict[str, Any] = field(default_factory=dict)
    python: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, str] = field(default_factory=dict)
    licence: dict[str, Any] = field(default_factory=dict)


def load(built_in: tuple) -> tuple:
    """Every adapter the folders hold, as backends; each one that cannot be loaded is skipped and
    kept in `SKIPPED` with its reason."""
    SKIPPED.clear()
    taken = {b.name for b in built_in}
    loaded = []
    for root in _roots():
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            try:
                manifest = read(folder, built_in)
                if manifest.name in taken:
                    raise AdapterRefused(f"the name {manifest.name!r} is already taken")
                loaded.append(backend_of(manifest))
                taken.add(manifest.name)
            except (AdapterRefused, OSError, tomllib.TOMLDecodeError) as exc:
                SKIPPED.append({"folder": str(folder), "reason": str(exc)})
    return tuple(loaded)


def _roots() -> list[Path]:
    raw = os.environ.get("SOLVER_ADAPTERS_DIR", DEFAULT_DIRS)
    return [Path(p) for p in raw.split(os.pathsep) if p and Path(p).is_dir()]


def ceiling(kind: str, built_in: tuple) -> tuple[frozenset[str], frozenset[str]]:
    """The classes and needs an adapter of this kind may claim at most."""
    if kind in ("ortools-engine", "command-line"):
        milp = next(b for b in built_in if b.name == "milp")
        return milp.classes, milp.provides
    return (frozenset().union(*(b.classes for b in built_in)),
            frozenset().union(*(b.provides for b in built_in)))


def read(folder: Path, built_in: tuple) -> Manifest:
    """A folder's manifest, checked; `AdapterRefused` names what is wrong."""
    path = folder / "adapter.toml"
    if not path.is_file():
        raise AdapterRefused("no adapter.toml")
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    name = raw.get("name")
    if not isinstance(name, str) or not _NAME.match(name):
        raise AdapterRefused("`name` must be lower-case letters, digits, - and _, starting with a letter")
    kind = raw.get("kind")
    if kind not in KINDS:
        raise AdapterRefused(f"`kind` must be one of {', '.join(KINDS)}, not {kind!r}")
    proves = raw.get("proves")
    if proves not in ("global", "local", "approximate"):
        raise AdapterRefused("`proves` must say what its `optimal` means: global, local or approximate")
    classes_max, provides_max = ceiling(kind, built_in)
    classes = _subset(raw, "classes", classes_max, kind)
    provides = _subset(raw, "provides", provides_max, kind)
    rank = raw.get("rank", DEFAULT_RANK)
    if not isinstance(rank, int) or isinstance(rank, bool) or rank < 0:
        raise AdapterRefused("`rank` must be a whole number, 0 or more")
    section = {"ortools-engine": "engine", "command-line": "command", "python": "python"}[kind]
    body = raw.get(section)
    if not isinstance(body, dict):
        raise AdapterRefused(f"a {kind} adapter needs a [{section}] table")
    if kind == "ortools-engine" and not (isinstance(body.get("engine"), str) and body["engine"].isupper()):
        raise AdapterRefused("[engine] `engine` must name an OR-Tools engine, such as CBC or GUROBI")
    if kind == "command-line":
        if not isinstance(body.get("executable"), str) or not isinstance(body.get("args", []), list):
            raise AdapterRefused("[command] needs `executable` and a list of `args`")
        if body.get("solution") not in SOLUTION_FORMATS:
            raise AdapterRefused(f"[command] `solution` must be one of {', '.join(SOLUTION_FORMATS)}")
        if "{model}" not in " ".join([body["executable"], *map(str, body.get("args", []))]):
            raise AdapterRefused("[command] must pass the model: `{model}` in `args`")
    if kind == "python":
        module = folder / str(body.get("module", ""))
        if not body.get("module") or not module.is_file() or module.parent.resolve() != folder.resolve():
            raise AdapterRefused("[python] `module` must name a .py file in the adapter's folder")
    environment = raw.get("environment", {})
    if not isinstance(environment, dict) or not all(isinstance(v, str) for v in environment.values()):
        raise AdapterRefused("[environment] values must be text")
    licence = raw.get("licence", {})
    if not isinstance(licence, dict) or not isinstance(licence.get("required", False), bool)             or not all(isinstance(v, str) for v in licence.get("env", []))             or bool(licence.get("file")) != bool(licence.get("file_env")):
        raise AdapterRefused("[licence] is `required` (true or false), `env` (names), and `file` with `file_env` together")
    return Manifest(
        name=name, kind=kind, version=str(raw.get("version", "")), proves=proves, classes=classes,
        provides=provides, rank=rank, note=str(raw.get("note", "")), folder=folder,
        engine=body if kind == "ortools-engine" else {}, command=body if kind == "command-line" else {},
        python=body if kind == "python" else {}, environment=environment, licence=licence,
    )


def _subset(raw: dict, key: str, allowed: frozenset[str], kind: str) -> frozenset[str]:
    if key not in raw:
        return allowed
    value = raw[key]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise AdapterRefused(f"`{key}` must be a list of words")
    beyond = set(value) - allowed
    if beyond:
        raise AdapterRefused(f"a {kind} adapter cannot claim {', '.join(sorted(beyond))} in `{key}`")
    return frozenset(value)


def backend_of(manifest: Manifest):
    """The registry row for an adapter."""
    from app.solve.backends import Backend

    solve, available = {
        "ortools-engine": _engine,
        "command-line": _command,
        "python": _python,
    }[manifest.kind](manifest)
    return Backend(
        name=manifest.name, classes=manifest.classes, provides=manifest.provides, rank=manifest.rank,
        solve=solve, proves=manifest.proves, is_available=available,
        note=manifest.note or f"{manifest.kind} adapter {manifest.name} {manifest.version}".strip(),
        planner_choice="An added solver will take this.",
        origin="adapter", automatic=False, manifest=manifest,
    )


# -- ortools-engine ------------------------------------------------------------------------


def _engine(manifest: Manifest) -> tuple[Callable, Callable[[], bool]]:
    engine = manifest.engine["engine"]
    options = manifest.engine.get("options")

    def available() -> bool:
        from ortools.linear_solver import pywraplp

        with _environment(manifest):
            return pywraplp.Solver.CreateSolver(engine) is not None

    def solve(compiled: Compiled, *, time_limit: float, workers: int, should_stop=None, seed=None,
              gap_rel: float = 0.0, on_progress=None, **_: Any) -> Solution:
        from app.solve import milp

        try:
            with _environment(manifest):
                result = milp.solve(compiled, time_limit=time_limit, workers=workers, should_stop=should_stop,
                                    seed=seed, gap_rel=gap_rel, engine=engine, options=options)
        except Exception as exc:
            raise AdapterFailed(f"{manifest.name}: {exc}") from exc
        return _named(result, manifest)

    return solve, available


# -- command-line --------------------------------------------------------------------------


def _command(manifest: Manifest) -> tuple[Callable, Callable[[], bool]]:
    command = manifest.command

    def executable() -> str | None:
        exe = command["executable"].format(adapter_dir=str(manifest.folder))
        if os.sep in exe or (os.altsep and os.altsep in exe):
            return exe if Path(exe).is_file() else None
        import shutil

        return shutil.which(exe, path=manifest.environment.get("PATH", os.environ.get("PATH")))

    def solve(compiled: Compiled, *, time_limit: float, workers: int, should_stop=None, seed=None,
              gap_rel: float = 0.0, on_progress=None, **_: Any) -> Solution:
        exe = executable()
        if exe is None:
            raise AdapterFailed(f"{manifest.name}: {command['executable']!r} is not installed here")
        return run_command(manifest, exe, compiled, time_limit=time_limit, workers=workers,
                           should_stop=should_stop, seed=seed, gap_rel=gap_rel)

    return solve, lambda: executable() is not None


def run_command(manifest: Manifest, exe: str, compiled: Compiled, *, time_limit: float, workers: int,
                should_stop=None, seed=None, gap_rel: float = 0.0) -> Solution:
    """Write the model as MPS, run the program, read its solution back. The objective is worked
    out here from the values, never read from the program; a status the program does not state
    is `feasible` at best -- an answer is not called optimal unless the solver said so."""
    from app.solve import mps
    from app.solve.milp import _read, _report

    keys = list(compiled.variables)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=f"adapter-{manifest.name}-") as tmp:
        model, solution = Path(tmp) / "model.mps", Path(tmp) / "model.sol"
        mps.write(compiled, model)
        values = {"model": str(model), "solution": str(solution), "time_limit": f"{time_limit:g}",
                  "threads": str(max(1, workers)), "gap": f"{gap_rel:g}", "seed": str(seed or 0),
                  "adapter_dir": str(manifest.folder)}
        argv = [exe, *(str(a).format(**values) for a in manifest.command.get("args", []))]
        with open(Path(tmp) / "out.txt", "wb") as out, open(Path(tmp) / "err.txt", "wb") as err:
            proc = subprocess.Popen(argv, cwd=tmp, stdout=out, stderr=err, env={**os.environ, **manifest.environment})
            deadline, stopped = started + time_limit + GRACE_S, False
            while proc.poll() is None:
                if not stopped and should_stop is not None and should_stop():
                    proc.terminate()
                    stopped = True
                if time.monotonic() > deadline:
                    proc.kill()
                    stopped = True
                time.sleep(0.05)
        code = proc.returncode
        status, found = _read_sol(solution) if solution.is_file() else (None, {})
        stderr = (Path(tmp) / "err.txt").read_text(errors="replace")[-400:].strip()
    if code in manifest.command.get("infeasible_exit_codes", []):
        status = "infeasible"
    elif code in manifest.command.get("unbounded_exit_codes", []):
        status = "unbounded"
    if status in ("optimal", "feasible") and not found:
        raise AdapterFailed(f"{manifest.name} said {status} and wrote no values")
    if status is None:
        if found:
            status = "feasible"
        elif stopped:
            status = "unknown"
        else:
            raise AdapterFailed(f"{manifest.name} exited {code} with no solution" + (f": {stderr}" if stderr else ""))
    wall = round(time.monotonic() - started, 3)
    if status not in ("optimal", "feasible"):
        return Solution(status=status, optimal=False, objective=None, assignments={}, wall_seconds=wall,
                        solver=_label(manifest))
    assignments = {key: _read(compiled.variables[key], found.get(f"v{i}", 0.0)) for i, key in enumerate(keys)}
    objective = (_report(compiled, float(compiled.objective.evaluated_at(assignments)))
                 if compiled.objective.coeffs else None)
    return Solution(status=status, optimal=status == "optimal", objective=objective, assignments=assignments,
                    best_bound=objective if status == "optimal" else None, wall_seconds=wall,
                    solver=_label(manifest))


_STATUS_LINE = re.compile(r"^#\s*status\s*[=:]\s*(\w+)", re.IGNORECASE)
_STATUSES = {"optimal": "optimal", "feasible": "feasible", "infeasible": "infeasible",
             "unbounded": "unbounded", "timelimit": "feasible", "time_limit": "feasible"}


def _read_sol(path: Path) -> tuple[str | None, dict[str, float]]:
    """The `sol` format -- Gurobi's, and what most solvers can write: `name value` per line,
    `#` comments. A `# Status = optimal` comment, when present, is the solver's own claim."""
    status, values = None, {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            match = _STATUS_LINE.match(line)
            if match:
                status = _STATUSES.get(match.group(1).lower(), status)
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                values[parts[0]] = float(parts[1])
            except ValueError:
                continue
    return status, values


# -- python ------------------------------------------------------------------------------


def _python(manifest: Manifest) -> tuple[Callable, Callable[[], bool]]:
    loaded: dict[str, Any] = {}

    def function() -> Callable | None:
        if "fn" not in loaded:
            path = manifest.folder / manifest.python["module"]
            try:
                spec = importlib.util.spec_from_file_location(f"solver_adapter_{manifest.name.replace('-', '_')}", path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                loaded["fn"] = getattr(module, manifest.python.get("function", "solve"), None)
            except Exception as exc:  # an adapter's import failing is its unavailability, not ours
                loaded["fn"], loaded["why"] = None, str(exc)
        return loaded["fn"]

    def solve(compiled: Compiled, **knobs: Any) -> Solution:
        fn = function()
        if fn is None:
            raise AdapterFailed(f"{manifest.name}: {loaded.get('why', 'its module has no solve function')}")
        try:
            with _environment(manifest):
                return _named(fn(compiled, **knobs), manifest)
        except (AdapterFailed, MemoryError):
            raise
        except Exception as exc:
            raise AdapterFailed(f"{manifest.name}: {type(exc).__name__}: {exc}") from exc

    return solve, lambda: function() is not None


# -- shared --------------------------------------------------------------------------------


class _environment:
    """The manifest's environment for the length of a call, restored after."""

    def __init__(self, manifest: Manifest):
        self.values, self.saved = manifest.environment, {}

    def __enter__(self):
        for key, value in self.values.items():
            self.saved[key] = os.environ.get(key)
            os.environ[key] = value

    def __exit__(self, *exc):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _label(manifest: Manifest) -> str:
    return f"{manifest.name} {manifest.version} (adapter)".replace("  ", " ")


def _named(result: Solution, manifest: Manifest) -> Solution:
    """The run records which adapter answered, whatever the engine calls itself."""
    from dataclasses import replace

    return replace(result, solver=f"{_label(manifest)}: {result.solver}")
