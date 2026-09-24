"""Each solve in a process of its own, with a memory ceiling, a CPU allowance and a deadline.

Target roadmap Phase 9 (Decision 4: one subprocess per run). A model that
asks for more memory than the machine has used to take the worker down with
it -- and every run it would have taken next. Here the solve runs in a child
process that cannot outgrow its limits, and whatever happens to the child
comes back to the worker as a run that failed with a reason, never as a
dead worker:

* **memory** -- `RLIMIT_AS` at `SOLVE_MEMORY_MB` (default 4096). An
  allocation past it fails in the child: "ran out of memory (limit 4096 MB)".
* **core files** -- none: the child is not dumpable (`PR_SET_DUMPABLE` 0),
  so a killed solve leaves no multi-gigabyte dump on the host.
* **CPU** -- `RLIMIT_CPU` at the run's time limit x its workers + 30 s. A
  solver that ignores its own clock is stopped by the kernel.
* **wall clock** -- the parent's own deadline, time limit + 15 s: SIGTERM,
  then SIGKILL 3 s later.

The child comes from a `forkserver` that has already imported the solvers,
so starting one costs a fork, not an interpreter and OR-Tools. Progress
events and a stop request cross the pipe as they did in-process: the
caller's `on_progress` and `should_stop` behave the same.

`SOLVE_SANDBOX=0` solves in-process instead -- for a platform without
`fork` (Windows development), where the limits cannot be set either.
"""

from __future__ import annotations

import importlib
import multiprocessing
import os
import signal
import sys
import time
from typing import Any, Callable

_GRACE_S = 15.0
_KILL_AFTER_S = 3.0

def _cpu_slack_s() -> int:
    """Seconds of CPU beyond time limit x workers (`SOLVE_CPU_SLACK_S`)."""
    return int(os.environ.get("SOLVE_CPU_SLACK_S", "30"))


_context = None


class SandboxFailed(Exception):
    """The child did not come back with an answer; the message says why."""


def enabled() -> bool:
    return os.environ.get("SOLVE_SANDBOX", "1") != "0" and sys.platform != "win32"


def memory_mb() -> int:
    return int(os.environ.get("SOLVE_MEMORY_MB", "4096"))


def _ctx():
    global _context
    if _context is None:
        _context = multiprocessing.get_context("forkserver")
        # Imported once in the server, inherited by every child it forks.
        _context.set_forkserver_preload(["app.solve.service", "app.solve.sandbox"])
    return _context


def run(
    target: str,
    kwargs: dict[str, Any],
    *,
    time_limit: float,
    workers: int = 1,
    deadline_s: float | None = None,
    on_progress: Callable[[str, dict], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Any:
    """Call `target` ("module:function") with `kwargs` in a sandboxed child
    and return what it returns; its own exceptions are raised here. The
    function is given `should_stop` and `on_progress` keyword arguments."""
    if not enabled():
        fn = _resolve(target)
        return fn(**kwargs, should_stop=should_stop, on_progress=on_progress)

    ctx = _ctx()
    limits = {"memory_mb": memory_mb(), "cpu_s": int(time_limit * max(1, workers)) + _cpu_slack_s()}
    parent, child = ctx.Pipe(duplex=False)
    stop = ctx.Event()
    process = ctx.Process(target=_child, args=(child, target, kwargs, limits, stop), daemon=True)
    process.start()
    child.close()
    deadline = time.monotonic() + (deadline_s if deadline_s is not None else time_limit + _GRACE_S)
    outcome: tuple | None = None
    try:
        while outcome is None:
            if should_stop is not None and should_stop() and not stop.is_set():
                stop.set()
            if time.monotonic() > deadline:
                _end(process)
                raise SandboxFailed(
                    f"the solver did not finish within {deadline_s or time_limit + _GRACE_S:.0f} s "
                    "of its time limit and was stopped"
                )
            if parent.poll(0.2):
                try:
                    message = parent.recv()
                except EOFError:
                    break
                if message[0] == "progress":
                    if on_progress is not None:
                        on_progress(message[1], message[2])
                else:
                    outcome = message
            elif not process.is_alive() and not parent.poll():
                break
    finally:
        parent.close()
        process.join(timeout=_KILL_AFTER_S)
        if process.is_alive():
            _end(process)

    if outcome is None:
        raise SandboxFailed(_why_it_died(process.exitcode, limits))
    kind, payload = outcome
    if kind == "result":
        return payload
    if kind == "memory":
        raise SandboxFailed(f"ran out of memory (limit {limits['memory_mb']} MB)")
    raise payload  # the child's own exception, e.g. Unsupported


def _end(process) -> None:
    process.terminate()
    process.join(timeout=_KILL_AFTER_S)
    if process.is_alive():
        process.kill()
        process.join()


def _why_it_died(exitcode: int | None, limits: dict) -> str:
    if exitcode is not None and exitcode < 0:
        number = -exitcode
        if number == signal.SIGXCPU:
            return f"used more than its CPU allowance of {limits['cpu_s']} s and was stopped"
        if number == signal.SIGKILL:
            return f"was killed -- most often for memory (limit {limits['memory_mb']} MB)"
        name = signal.Signals(number).name
        # A native allocation failing under RLIMIT_AS aborts rather than
        # raising MemoryError.
        return f"the solver crashed ({name}); the memory limit is {limits['memory_mb']} MB"
    return f"the solver process ended without an answer (exit code {exitcode})"


def _resolve(target: str) -> Callable[..., Any]:
    module, _, name = target.partition(":")
    return getattr(importlib.import_module(module), name)


_MEMORY_WORDS = ("memory", "failed to map", "cannot allocate", "bad_alloc")


def _looks_like_memory(exc: BaseException) -> bool:
    """Under RLIMIT_AS a failed allocation does not always say MemoryError: a
    library's mmap fails (OSError ENOMEM), an extension will not load
    ("failed to map segment"), C++ throws bad_alloc. Any of these, anywhere
    in the chain, is the memory ceiling."""
    import errno

    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, MemoryError):
            return True
        if isinstance(exc, OSError) and exc.errno == errno.ENOMEM:
            return True
        if any(word in str(exc).lower() for word in _MEMORY_WORDS):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def _no_core_dump() -> None:  # pragma: no cover -- in the child
    from app.solve.nodump import forbid

    forbid()


def _child(conn, target: str, kwargs: dict, limits: dict, stop) -> None:  # pragma: no cover -- in the child
    # Loaded before the ceiling: importing the code is not the solve.
    fn = _resolve(target)
    try:
        import resource

        memory = limits["memory_mb"] * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_CPU, (limits["cpu_s"], limits["cpu_s"] + 5))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ImportError, ValueError, OSError):
        pass
    _no_core_dump()

    def progress(kind: str, payload: dict) -> None:
        conn.send(("progress", kind, payload))

    try:
        result = fn(**kwargs, should_stop=stop.is_set, on_progress=progress)
        conn.send(("result", result))
    except BaseException as exc:  # noqa: BLE001 -- carried to the parent, raised there
        if _looks_like_memory(exc):
            conn.send(("memory", None))
            return
        try:
            conn.send(("raise", exc))
        except Exception:
            conn.send(("raise", RuntimeError(f"{type(exc).__name__}: {exc}")))
    finally:
        conn.close()


# -- what runs in the child ----------------------------------------------------------


def solve_in_child(*, backend: str, compiled, time_limit: float, seed, workers: int, gap_rel: float,
                   should_stop, on_progress, hint=None, symmetry=False):
    """`solve_compiled`, by backend name (a registry entry does not cross a pipe)."""
    from app.solve.backends import by_name
    from app.solve.service import solve_compiled

    return solve_compiled(
        by_name(backend), compiled, time_limit=time_limit, seed=seed, should_stop=should_stop,
        workers=workers, gap_rel=gap_rel, on_progress=on_progress, hint=hint, symmetry=symmetry,
    )


def pareto_in_child(*, backend: str, compiled, steps: int, time_limit: float, seed, workers: int,
                    gap_rel: float, should_stop, on_progress):
    """`pareto.front`, by backend name: every solve of it is `solve_compiled`."""
    from app.solve.backends import by_name
    from app.solve.pareto import front
    from app.solve.service import solve_compiled

    chosen = by_name(backend)

    def solve(model, limit):
        return solve_compiled(chosen, model, time_limit=limit, seed=seed, should_stop=should_stop,
                              workers=workers, gap_rel=gap_rel)[0]

    return front(chosen, compiled, steps=steps, time_limit=time_limit, solve=solve)


def explain_in_child(*, backend: str, compiled, probe_seconds: float, should_stop, on_progress):
    from app.solve.backends import by_name
    from app.solve.diagnose import explain
    from app.solve.reformulate import bigm, pwl_rewrite

    chosen = by_name(backend)
    if "indicator" not in chosen.provides and any(c.when for c in compiled.constraints):
        compiled, _ = bigm(compiled)
    solve = chosen.solve
    if compiled.pwl and "pwl-native" not in chosen.provides:
        # Rewritten per probe, so the curve's own rows are never offered as
        # rules that might be in conflict.
        def solve(probe, **kwargs):  # noqa: F811
            return chosen.solve(pwl_rewrite(probe)[0], **kwargs)
    from app.solve import cpsat, highs

    # Cores to start from, confirmed and shrunk with `chosen` so the verdicts
    # stay its. CP-SAT's own assumptions first when it ran -- exact for the
    # whole-number model -- then HiGHS's IIS of the linear relaxation, for
    # any backend.
    cores = [("iis", lambda model: highs.iis(model, time_limit=probe_seconds * 4))]
    if chosen.name == "cp-sat":
        cores.insert(0, ("cp-sat", lambda model: cpsat.core(model, time_limit=probe_seconds * 4)))
    return explain(compiled, solve, probe_seconds=probe_seconds, cores=cores)
