"""Solvers added from a manifest (queue R41, app.solve.adapters): the three reference adapters stand
in for commercial ones -- CBC through OR-Tools (as Gurobi, Xpress or CPLEX would arrive), HiGHS as a
separate program (MPS in, a solution file out), and a python function -- and every one must give
the golden suite's known answers through the path a run takes."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.solve import adapters, compile_model
from app.solve.backends import BUILT_IN, NoBackend, choose
from app.solve.classify import classify
from app.solve.convexity import refine
from app.solve.service import solve_compiled
from tests.test_golden import GOLDEN, NO_DATA

REFERENCE = Path(__file__).resolve().parent.parent / "adapters" / "reference"


@pytest.fixture(scope="module")
def loaded():
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SOLVER_ADAPTERS_DIR", str(REFERENCE))
        found = {b.name: b for b in adapters.load(BUILT_IN)}
    assert adapters.SKIPPED == []
    return found


def _takes(backend, found) -> bool:
    return found.model_class in backend.classes and not (found.needs - backend.provides)


def _cases():
    for name, ir, status, objective in GOLDEN:
        yield pytest.param(ir, status, objective, id=name)


@pytest.mark.parametrize("adapter", ["cbc", "highs-cli", "python-cpsat"])
@pytest.mark.parametrize("ir, status, objective", list(_cases()))
def test_every_reference_adapter_gives_the_known_answers(loaded, adapter, ir, status, objective):
    backend = loaded[adapter]
    compiled = compile_model(ir, NO_DATA)
    if not _takes(backend, refine(classify(ir, NO_DATA), compiled)):
        pytest.skip(f"{adapter} does not take this model")
    result, reason = solve_compiled(backend, compiled, time_limit=20, seed=1)
    assert result.status == status, reason
    if objective is not None:
        got = Decimal(str(result.objective))
        assert abs(got - objective) <= Decimal("1e-6") * max(Decimal(1), abs(objective)), got
    assert f"{adapter}" in result.solver and "(adapter)" in result.solver


def test_an_adapter_is_listed_as_added_and_is_not_chosen_unasked(loaded):
    backend = loaded["cbc"]
    assert backend.origin == "adapter" and backend.automatic is False and backend.is_available()
    ir, _, _ = GOLDEN[0][1], None, None
    found = refine(classify(ir, NO_DATA), compile_model(ir, NO_DATA))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("app.solve.backends.REGISTRY", BUILT_IN + tuple(loaded.values()))
        chosen, _ = choose(found)
        assert chosen.origin == "built-in"
        if _takes(backend, found):
            assert choose(found, "cbc")[0] is backend


def _manifest(tmp_path: Path, name: str, text: str) -> Path:
    folder = tmp_path / name
    folder.mkdir()
    (folder / "adapter.toml").write_text(text, encoding="utf-8")
    return folder


@pytest.mark.parametrize("text, reason", [
    ('name = "x"\nkind = "ortools-engine"\n[engine]\nengine = "CBC"\n', "proves"),
    ('name = "x"\nkind = "telepathy"\nproves = "global"\n', "kind"),
    ('name = "X!"\nkind = "python"\nproves = "global"\n', "name"),
    ('name = "x"\nkind = "command-line"\nproves = "global"\nprovides = ["quadratic"]\n'
     '[command]\nexecutable = "x"\nargs = ["{model}"]\nsolution = "sol"\n', "cannot claim quadratic"),
    ('name = "x"\nkind = "python"\nproves = "global"\nprovides = ["telepathy"]\n[python]\nmodule = "a.py"\n',
     "cannot claim telepathy"),
    ('name = "x"\nkind = "command-line"\nproves = "global"\n[command]\nexecutable = "x"\nargs = []\nsolution = "sol"\n',
     "{model}"),
    ('name = "x"\nkind = "python"\nproves = "global"\n[python]\nmodule = "../escape.py"\n', "module"),
    ('name = "milp"\nkind = "ortools-engine"\nproves = "global"\n[engine]\nengine = "CBC"\n', "already taken"),
    ('this is not toml', ""),
])
def test_a_manifest_that_cannot_be_loaded_is_skipped_with_its_reason(tmp_path, monkeypatch, text, reason):
    _manifest(tmp_path, "bad", text)
    _manifest(tmp_path, "good", 'name = "good"\nkind = "ortools-engine"\nproves = "global"\n[engine]\nengine = "CBC"\n')
    monkeypatch.setenv("SOLVER_ADAPTERS_DIR", str(tmp_path))
    loaded = adapters.load(BUILT_IN)
    assert [b.name for b in loaded] == ["good"]
    (skipped,) = adapters.SKIPPED
    assert skipped["folder"].endswith("bad") and reason in skipped["reason"]


def test_an_adapter_whose_solver_is_not_installed_is_unavailable_and_refused_by_name(tmp_path, monkeypatch):
    _manifest(tmp_path, "gurobi", 'name = "gurobi"\nkind = "ortools-engine"\nproves = "global"\n'
                                  '[engine]\nengine = "GUROBI"\n')
    _manifest(tmp_path, "missing-cli", 'name = "missing-cli"\nkind = "command-line"\nproves = "global"\n'
                                       '[command]\nexecutable = "no-such-solver"\nargs = ["{model}"]\nsolution = "sol"\n')
    monkeypatch.setenv("SOLVER_ADAPTERS_DIR", str(tmp_path))
    loaded = {b.name: b for b in adapters.load(BUILT_IN)}
    assert not loaded["gurobi"].is_available() and not loaded["missing-cli"].is_available()
    ir = GOLDEN[0][1]
    found = refine(classify(ir, NO_DATA), compile_model(ir, NO_DATA))
    monkeypatch.setattr("app.solve.backends.REGISTRY", BUILT_IN + tuple(loaded.values()))
    with pytest.raises(NoBackend, match="gurobi is not available"):
        choose(found, "gurobi")


def test_a_command_line_solver_that_says_nothing_is_not_called_optimal(tmp_path, monkeypatch):
    """A program that writes values and no status: the answer is `feasible`, never `optimal`."""
    folder = _manifest(tmp_path, "quiet", 'name = "quiet"\nkind = "command-line"\nproves = "global"\n'
                                          '[command]\nexecutable = "python3"\n'
                                          'args = ["{adapter_dir}/quiet.py", "{model}", "{solution}"]\nsolution = "sol"\n')
    (folder / "quiet.py").write_text("import sys\nopen(sys.argv[2], 'w').write('v0 1\\n')\n", encoding="utf-8")
    monkeypatch.setenv("SOLVER_ADAPTERS_DIR", str(tmp_path))
    (quiet,) = adapters.load(BUILT_IN)
    ir = GOLDEN[0][1]
    compiled = compile_model(ir, NO_DATA)
    result = quiet.solve(compiled, time_limit=5, workers=1)
    assert result.status == "feasible" and not result.optimal and result.best_bound is None


def test_a_command_line_solver_is_stopped_at_its_time_limit(tmp_path, monkeypatch):
    folder = _manifest(tmp_path, "slow", 'name = "slow"\nkind = "command-line"\nproves = "global"\n'
                                         '[command]\nexecutable = "python3"\n'
                                         'args = ["{adapter_dir}/slow.py", "{model}"]\nsolution = "sol"\n')
    (folder / "slow.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    monkeypatch.setenv("SOLVER_ADAPTERS_DIR", str(tmp_path))
    monkeypatch.setattr(adapters, "GRACE_S", 0.5)
    (slow,) = adapters.load(BUILT_IN)
    result = slow.solve(compile_model(GOLDEN[0][1], NO_DATA), time_limit=0.5, workers=1)
    assert result.status == "unknown" and result.wall_seconds < 5
