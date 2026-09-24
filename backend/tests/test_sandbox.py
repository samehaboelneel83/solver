"""Each solve in a sandboxed child (target roadmap Phase 9, app.solve.sandbox).

The targets below run in the child; each shows one way a solve can go
wrong, and that the parent -- the worker -- comes back with a reason."""

from __future__ import annotations

import os
import signal
import time

import pytest
from sqlalchemy import text

from app.seed import seed_workforce_demo
from app.solve import sandbox
from app.solve.service import enqueue_run
from app.worker import work_once
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401

pytestmark = pytest.mark.skipif(not sandbox.enabled(), reason="no fork on this platform")

HERE = "tests.test_sandbox"


def dumpable(*, should_stop, on_progress):
    import ctypes

    return ctypes.CDLL(None).prctl(3, 0, 0, 0, 0)  # PR_GET_DUMPABLE


def answer(*, value, should_stop, on_progress):
    on_progress("incumbent", {"t": 0.1, "objective": 3.0})
    on_progress("bound", {"t": 0.2, "bound": 2.0})
    return {"value": value, "pid": os.getpid()}


def refuse(*, should_stop, on_progress):
    raise ValueError("this model says no")


def hog(*, should_stop, on_progress):
    chunks = [bytearray(64 * 1024 * 1024) for _ in range(64)]  # 4 GB
    return len(chunks)


def spin(*, should_stop, on_progress):
    while True:
        pass


def linger(*, should_stop, on_progress):
    time.sleep(60)


def die(*, should_stop, on_progress):
    os.kill(os.getpid(), signal.SIGKILL)


def wait_to_be_told(*, should_stop, on_progress):
    started = time.monotonic()
    while not should_stop():
        if time.monotonic() - started > 20:
            return "never told"
        time.sleep(0.05)
    return "stopped"


def test_the_answer_and_its_progress_come_back_from_another_process():
    heard = []
    result = sandbox.run(f"{HERE}:answer", {"value": 42}, time_limit=5, on_progress=lambda k, p: heard.append(k))
    assert result["value"] == 42 and result["pid"] != os.getpid()
    assert heard == ["incumbent", "bound"]


def test_the_child_s_own_exception_is_raised_in_the_parent():
    with pytest.raises(ValueError, match="this model says no"):
        sandbox.run(f"{HERE}:refuse", {}, time_limit=5)


def test_running_out_of_memory_is_a_reason_not_a_dead_worker(monkeypatch):
    monkeypatch.setenv("SOLVE_MEMORY_MB", "512")
    with pytest.raises(sandbox.SandboxFailed, match="memory"):
        sandbox.run(f"{HERE}:hog", {}, time_limit=5)


def test_a_solve_past_its_cpu_allowance_is_stopped_by_the_kernel(monkeypatch):
    monkeypatch.setenv("SOLVE_CPU_SLACK_S", "1")
    started = time.monotonic()
    with pytest.raises(sandbox.SandboxFailed, match="CPU allowance of 2 s"):
        sandbox.run(f"{HERE}:spin", {}, time_limit=1, workers=1, deadline_s=30)
    assert time.monotonic() - started < 15


def test_a_solve_past_its_deadline_is_killed():
    started = time.monotonic()
    with pytest.raises(sandbox.SandboxFailed, match="did not finish within 1 s"):
        sandbox.run(f"{HERE}:linger", {}, time_limit=1, deadline_s=1)
    assert time.monotonic() - started < 10


def test_a_child_killed_outright_is_reported():
    with pytest.raises(sandbox.SandboxFailed, match="was killed"):
        sandbox.run(f"{HERE}:die", {}, time_limit=5)


def test_a_stop_request_reaches_the_child():
    asked = time.monotonic() + 0.5
    result = sandbox.run(f"{HERE}:wait_to_be_told", {}, time_limit=30, should_stop=lambda: time.monotonic() > asked)
    assert result == "stopped"


def test_a_child_that_ignores_a_stop_is_ended_at_once_when_abandoned():
    """A portfolio's beaten entrant: a solver that never looks at `should_stop` must not run to its limit."""
    started = time.monotonic()
    asked = started + 0.3
    with pytest.raises(sandbox.Abandoned):
        sandbox.run(f"{HERE}:linger", {}, time_limit=30, abandon=lambda: time.monotonic() > asked)
    assert time.monotonic() - started < 5


def test_a_run_that_runs_out_of_memory_fails_with_a_reason_and_the_worker_goes_on(
    db, empty_queue, monkeypatch  # noqa: F811
):
    seeded = seed_workforce_demo(db)
    starved = enqueue_run(db, seeded["scenario_id"], time_limit=10.0)
    monkeypatch.setenv("SOLVE_MEMORY_MB", "64")
    assert work_once(db) == starved
    row = db.execute(text("SELECT status, error FROM run WHERE id = :r"), {"r": starved}).mappings().one()
    assert row["status"] == "error"
    assert "memory" in row["error"] or "crashed" in row["error"], row["error"]

    monkeypatch.delenv("SOLVE_MEMORY_MB")
    fed = enqueue_run(db, seeded["scenario_id"], time_limit=10.0)
    assert work_once(db) == fed
    assert db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": fed}).scalar_one() in ("optimal", "feasible")


def test_a_killed_solve_leaves_no_core_file():
    """Under Docker Desktop a core dump lands on the host's disk: ten of a
    solver's filled 13.8 GB of C: on 2026-09-23."""
    assert sandbox.run(f"{HERE}:dumpable", {}, time_limit=5) == 0


def test_the_highs_worker_is_not_dumpable_either():
    """It is started as a new program, and `exec` resets the flag: a HiGHS
    worker killed at its CPU limit left a 0.9 GB dump on 2026-09-24."""
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-c", "import ctypes, app.solve.highs_worker; print(ctypes.CDLL(None).prctl(3, 0, 0, 0, 0))"],
        capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "0"
